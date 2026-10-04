"""The exit tunnel: recording the inspection that gates a cup's settlement."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import require
from response import envelope, paginate
from services.core import get_order, new_record, recompute_store, rh, touch
from services.wall import order_variance, recompute_shrinkage
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("exit_inspections", __name__)


@bp.route("/stores/exit-inspections", methods=["POST"])
def record_inspection():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "fusion_order_id", "outcome", "checklist_result",
                   "reviewed_by_user_id")

    order = get_order(payload["fusion_order_id"])

    expected = payload.get("expected_fusion_order_version")
    if expected is not None and int(expected) != order["version"]:
        fail("ERR_INSPECTION_STALE_VERSION",
             "expected_fusion_order_version no longer matches the cup's version.")

    outcome = payload["outcome"]
    if outcome not in ("CLEAR", "MISMATCH"):
        fail("ERR_CONSTRAINT_VIOLATION", "outcome must be CLEAR or MISMATCH.")
    checklist = payload["checklist_result"]
    if checklist not in ("COMPLETED", "PARTIAL", "WAIVED"):
        fail("ERR_CONSTRAINT_VIOLATION",
             "checklist_result must be COMPLETED, PARTIAL or WAIVED.")

    order["variance_grams"] = order_variance(order["id"])

    variance = order_variance(order["id"])
    absolute = variance if variance >= 0 else -variance
    variance_bps = 0
    if order["declared_mass_grams"] > 0:
        variance_bps = rh(absolute * 10000 / order["declared_mass_grams"])

    inspection = new_record({
        "fusion_order_id": order["id"],
        "outcome": outcome,
        "checklist_result": checklist,
        "reviewed_by_user_id": payload["reviewed_by_user_id"],
        "variance_bps": variance_bps,
        "stage": "COMPLETED",
    })
    db().exit_inspections[inspection["id"]] = inspection

    store = db().stores.get(order["store_id"])
    if order["status"] == "CLOSED" and outcome == "CLEAR":
        order["status"] = "SETTLED"
    touch(order)
    if store is not None:
        recompute_shrinkage(store)
        recompute_store(store)
        touch(store)
    return envelope(out(inspection), status=201)


@bp.route("/stores/exit-inspections", methods=["GET"])
def list_inspections():
    require("StoreAssociate")
    params = list_params()
    items = [i for i in db().exit_inspections.values()
             if matches(i, params, "fusion_order_id", "stage")]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/exit-inspections/<inspection_id>", methods=["GET"])
def read_inspection(inspection_id):
    require("StoreAssociate")
    inspection = db().exit_inspections.get(inspection_id)
    if inspection is None:
        fail("ERR_NOT_FOUND", "No exit inspection exists with id %s." % inspection_id)
    return envelope(out(inspection))