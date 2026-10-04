"""ServiceDisruption endpoints."""
from flask import Blueprint

from core import (
    ApiError,
    body,
    db,
    dump,
    endpoint,
    f_dt,
    f_enum,
    f_str,
    forbid_unless_owner_host,
    new_row,
    now,
    paginate,
    q_enum,
    q_str,
    respond_object,
    sort_created,
    touch,
)
import svc

bp = Blueprint("disruptions", __name__, url_prefix="/rail/service-disruptions")


@bp.post("")
@endpoint("HostRailroadRep")
def create_disruption():
    payload = body()
    corridor_id = f_str(payload, "corridor_id")
    disruption_type = f_enum(payload, "disruption_type", svc.DISRUPTION_TYPES)
    started_at = f_dt(payload, "started_at")
    reaccommodation_policy = f_enum(
        payload, "reaccommodation_policy", svc.REACCOMMODATION_POLICIES
    )
    corridor = svc.need_corridor(corridor_id)
    forbid_unless_owner_host(corridor["host_railroad_id"])
    row = new_row(
        "service_disruption",
        corridor_id=corridor_id,
        disruption_type=disruption_type,
        started_at=started_at,
        cleared_at=None,
        reaccommodation_policy=reaccommodation_policy,
        bus_bridge_active=False,
        status="OPEN",
    )
    db.service_disruptions[row["id"]] = row
    return respond_object(dump(row), status=201)


@bp.get("")
@endpoint()
def list_disruptions():
    rows = list(db.service_disruptions.values())
    corridor_id = q_str("corridor_id")
    status = q_enum("status", svc.DISRUPTION_STATUSES)
    if corridor_id is not None:
        rows = [r for r in rows if r["corridor_id"] == corridor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(sort_created(rows))


@bp.get("/<rid>")
@endpoint()
def get_disruption(rid):
    row = svc.need_disruption(rid)
    return respond_object(dump(row))


@bp.post("/<rid>/bridge")
@endpoint("HostRailroadRep")
def bridge_disruption(rid):
    row = svc.need_disruption(rid)
    corridor = svc.need_corridor(row["corridor_id"])
    forbid_unless_owner_host(corridor["host_railroad_id"])
    if row["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Disruption is not OPEN.")
    row["status"] = "BRIDGED"
    row["bus_bridge_active"] = True
    touch(row)
    svc.disruption_bridge_cascade(row)
    return respond_object(dump(row))


@bp.post("/<rid>/recover")
@endpoint("HostRailroadRep")
def recover_disruption(rid):
    row = svc.need_disruption(rid)
    corridor = svc.need_corridor(row["corridor_id"])
    forbid_unless_owner_host(corridor["host_railroad_id"])
    if row["status"] != "BRIDGED":
        raise ApiError("ERR_INVALID_STATE", "Disruption is not BRIDGED.")
    row["status"] = "RECOVERED"
    row["bus_bridge_active"] = False
    row["cleared_at"] = now()
    touch(row)
    return respond_object(dump(row))
