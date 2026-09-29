"""Maintenance events, derates and the resequencing loop (PRD 3.8)."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

import cascades
import serializers as ser
from calc import MAINTENANCE_BUFFER_HOURS, NOTICE_HOURS, notification_scope
from core import (ZERO, apply_filters, authenticate, bad_request, db, fail,
                  field_decimal, field_enum, field_instant, field_string, get_body,
                  lookup_path, new_row, now, paginate, present, resolve_ref,
                  respond_object, r2, touch)

bp = Blueprint("maintenance", __name__)

ALL_ROLES = ("PipelineScheduler", "TariffAdministrator", "TerminalOperator", "Shipper")
KINDS = ("PIGGING", "INTEGRITY_DIG", "HYDROTEST", "VALVE_REPAIR")
BLOCKING = ("PLANNED", "NOTIFIED", "ACTIVE")


def get_event(row_id):
    return lookup_path(db.maintenance_events, row_id, "ERR_MAINTENANCE_EVENT_NOT_FOUND")


@bp.route("/pipeline/maintenance-events", methods=["POST"])
def create_event():
    authenticate(("PipelineScheduler",))
    body = get_body()
    segment = resolve_ref(body, "segment_id", db.segments)
    if segment is None:
        bad_request("Required field 'segment_id' is missing.")
    kind = field_enum(body, "kind", KINDS)
    start = field_instant(body, "window_start")
    end = field_instant(body, "window_end")
    derate = field_decimal(body, "capacity_derate_pct", positive=True)
    if derate > 1:
        bad_request("'capacity_derate_pct' must be no greater than 1.")
    notes = None
    if present(body, "notes"):
        notes = field_string(body, "notes")
    if end <= start:
        fail("ERR_INVALID_WINDOW",
             "'window_end' must be strictly later than 'window_start'.")
    buffer_span = timedelta(hours=MAINTENANCE_BUFFER_HOURS)
    for peer in db.maintenance_events.values():
        if peer["segment_id"] != segment["id"] or peer["status"] not in BLOCKING:
            continue
        if start <= peer["window_end"] + buffer_span and peer["window_start"] <= end + buffer_span:
            fail("ERR_MAINTENANCE_WINDOW_CONFLICT",
                 "The window conflicts with maintenance event {} within the 24-hour "
                 "buffer.".format(peer["id"]))
    row = new_row({
        "segment_id": segment["id"],
        "kind": kind,
        "window_start": start,
        "window_end": end,
        "capacity_derate_pct": r2(derate),
        "status": "PLANNED",
        "notified_at": None,
        "notified_shipper_count": 0,
        "notes": notes,
    })
    db.maintenance_events[row["id"]] = row
    return respond_object(ser.maintenance_json(row), 201)


@bp.route("/pipeline/maintenance-events/<row_id>/notify", methods=["POST"])
def notify(row_id):
    authenticate(("PipelineScheduler",))
    event = get_event(row_id)
    get_body()
    if event["status"] != "PLANNED":
        fail("ERR_MAINTENANCE_INVALID_STATE",
             "Only a PLANNED event can be notified, not {}.".format(event["status"]))
    if now() + timedelta(hours=NOTICE_HOURS) > event["window_start"]:
        fail("ERR_INSUFFICIENT_NOTICE",
             "Notice must be issued at least 48 hours before the window starts.")
    scope = notification_scope(event)
    event["status"] = "NOTIFIED"
    event["notified_at"] = now()
    event["notified_shipper_count"] = scope
    touch(event)
    cascades.maintenance_derate_cascade(event, db.segments[event["segment_id"]])
    return respond_object(ser.maintenance_json(event))


@bp.route("/pipeline/maintenance-events/<row_id>/start", methods=["POST"])
def start_event(row_id):
    authenticate(("PipelineScheduler",))
    event = get_event(row_id)
    get_body()
    if event["status"] != "NOTIFIED":
        fail("ERR_MAINTENANCE_INVALID_STATE",
             "Only a NOTIFIED event can be started, not {}.".format(event["status"]))
    event["status"] = "ACTIVE"
    touch(event)
    cascades.maintenance_derate_cascade(event, db.segments[event["segment_id"]])
    return respond_object(ser.maintenance_json(event))


@bp.route("/pipeline/maintenance-events/<row_id>/complete", methods=["POST"])
def complete_event(row_id):
    authenticate(("PipelineScheduler",))
    event = get_event(row_id)
    get_body()
    if event["status"] != "ACTIVE":
        fail("ERR_MAINTENANCE_INVALID_STATE",
             "Only an ACTIVE event can be completed, not {}.".format(event["status"]))
    event["status"] = "COMPLETED"
    touch(event)
    cascades.maintenance_restore_cascade(event, db.segments[event["segment_id"]])
    return respond_object(ser.maintenance_json(event))


@bp.route("/pipeline/maintenance-events/<row_id>", methods=["GET"])
def read_event(row_id):
    authenticate(ALL_ROLES)
    return respond_object(ser.maintenance_json(get_event(row_id)))


@bp.route("/pipeline/maintenance-events", methods=["GET"])
def list_events():
    authenticate(ALL_ROLES)
    rows = apply_filters(list(db.maintenance_events.values()), [
        ("segment_id", "segment_id", "str"),
        ("status", "status", "str"),
    ])
    rows.sort(key=lambda r: (r["window_start"], r["created_at"], r["_seq"]))
    return paginate(rows, ser.maintenance_json)
