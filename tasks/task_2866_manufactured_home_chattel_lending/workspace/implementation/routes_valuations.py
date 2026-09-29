"""Valuation creation, certification and reads (PRD 3.3)."""

from flask import Blueprint, request

import constants as K
import core
import domain
import envelope
import security
import shape
import store
from errors import ApiError
from routes_units import query_enum

bp = Blueprint("valuations", __name__)

VALUER_ROLES = (security.CREDIT_ANALYST, security.RECOVERY_MANAGER)


@bp.post("/valuations")
def create_valuation():
    security.require(*VALUER_ROLES)
    data = shape.body()

    unit = store.get_unit(shape.req_id(data, "unit_id"))
    guide = store.get_guide(shape.req_id(data, "guide_id"))

    variant = shape.req_enum(data, "variant", K.VALUATION_VARIANTS)
    expected_unit_version = shape.req_int(data, "expected_unit_version")

    if guide["effective_date"] > core.now():
        raise ApiError("ERR_GUIDE_NOT_EFFECTIVE")

    if expected_unit_version != unit["version"]:
        raise ApiError("ERR_STALE_UNIT_VERSION")

    record = {
        "id": core.new_id(),
        "unit_id": unit["id"],
        "guide_id": guide["id"],
        "variant": variant,
        "status": "DRAFT",
        "certified_by_user_id": None,
        "certified_at": None,
    }
    record.update(domain.compute_valuation(unit, guide, variant))
    store.stamp_new(record)
    store.valuations[record["id"]] = record

    # a new valuation retires the prior certified valuation of the same variant
    for other in store.ordered(list(store.valuations.values())):
        if (other["id"] != record["id"] and other["unit_id"] == unit["id"]
                and other["variant"] == variant and other["status"] == "CERTIFIED"):
            other["status"] = "SUPERSEDED"
            store.touch(other)

    store.touch(unit)
    return envelope.created(store.serialize(record))


@bp.get("/valuations/<valuation_id>")
def read_valuation(valuation_id):
    security.require(*security.STAFF)
    return envelope.ok(store.serialize(store.get_valuation(valuation_id)))


@bp.get("/valuations")
def list_valuations():
    security.require(*security.STAFF)
    unit_id = request.args.get("unit_id")
    guide_id = request.args.get("guide_id")
    variant = query_enum("variant", K.VALUATION_VARIANTS)
    status = query_enum("status", K.VALUATION_STATUSES)

    rows = store.ordered(list(store.valuations.values()))
    if unit_id:
        rows = [v for v in rows if v["unit_id"] == unit_id]
    if guide_id:
        rows = [v for v in rows if v["guide_id"] == guide_id]
    if variant:
        rows = [v for v in rows if v["variant"] == variant]
    if status:
        rows = [v for v in rows if v["status"] == status]
    return envelope.paginate(rows, store.serialize)


@bp.post("/valuations/<valuation_id>/certify")
def certify_valuation(valuation_id):
    actor = security.require(*VALUER_ROLES)
    valuation = store.get_valuation(valuation_id)
    if valuation["status"] != "DRAFT":
        raise ApiError("ERR_VALUATION_NOT_CERTIFIABLE")
    valuation["status"] = "CERTIFIED"
    valuation["certified_by_user_id"] = actor.user_id
    valuation["certified_at"] = core.now()
    store.touch(valuation)
    return envelope.ok(store.serialize(valuation))
