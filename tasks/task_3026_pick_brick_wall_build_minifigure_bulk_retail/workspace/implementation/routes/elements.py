"""The element catalogue: registration, retirement, the archive and reissue."""

from flask import Blueprint

from db import db
from errors import fail
from middleware import require
from response import envelope, paginate
from services.core import get_element, new_record, touch
from services.wall import element_bin_occupied
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("elements", __name__)


def _check_version(record, payload, field):
    expected = payload.get(field)
    if expected is not None and int(expected) != record["version"]:
        fail("ERR_STALE_VERSION",
             "%s no longer matches the current version of the resource." % field)


@bp.route("/stores/elements", methods=["POST"])
def create_element():
    require("PlatformAdmin")
    payload = body()
    require_fields(payload, "element_code", "element_name", "theme",
                   "unit_mass_grams", "cost_basis_cents")

    mass = float(payload["unit_mass_grams"])
    if mass <= 0:
        fail("ERR_CONSTRAINT_VIOLATION", "unit_mass_grams must be greater than zero.")
    cost = int(payload["cost_basis_cents"])
    if cost < 0:
        fail("ERR_CONSTRAINT_VIOLATION", "cost_basis_cents may not be negative.")

    code = payload["element_code"]
    for existing in db().elements.values():
        if existing["element_code"] == code:
            fail("ERR_CONSTRAINT_VIOLATION", "An element code must be globally unique.")

    element = new_record({
        "element_code": code,
        "element_name": payload["element_name"],
        "theme": payload["theme"],
        "unit_mass_grams": mass,
        "cost_basis_cents": cost,
        "make_ready_lead_days": int(payload.get("make_ready_lead_days", 5)),
        "sourcing_mode": "CURRENT_PRODUCTION",
        "status": "PENDING_CATALOG",
    })
    db().elements[element["id"]] = element
    return envelope(out(element), status=201)


@bp.route("/stores/elements", methods=["GET"])
def list_elements():
    require("PlatformAdmin", "StoreAssociate")
    params = list_params()
    items = [e for e in db().elements.values() if matches(e, params, "status", "theme")]
    items.sort(key=lambda e: (e["created_at"], e["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/elements/<element_id>", methods=["GET"])
def read_element(element_id):
    require("PlatformAdmin", "StoreAssociate", "Member")
    return envelope(out(get_element(element_id)))


@bp.route("/stores/elements/<element_id>/retire", methods=["POST"])
def retire_element(element_id):
    require("StoreAssociate")
    payload = body()
    element = get_element(element_id)

    _check_version(element, payload, "expected_element_version")

    if element["status"] not in ("ACTIVE", "PENDING_CATALOG"):
        fail("ERR_INVALID_STATE",
             "Only an active or newly registered element may be retired.")

    if element_bin_occupied(element["id"]):
        fail("ERR_ELEMENT_BIN_OCCUPIED",
             "A bin still holds mass of this element.")

    for order in db().fusion_orders.values():
        if (order.get("pieced_element_id") == element["id"]
                and order["status"] == "PENDING"):
            fail("ERR_ELEMENT_BIN_OCCUPIED",
                 "A pending per-piece cup is still priced against this element.")

    element["status"] = "RETIRED_TO_ARCHIVE"
    element["sourcing_mode"] = "SURPLUS"
    touch(element)
    return envelope(out(element))


@bp.route("/stores/elements/<element_id>/reissue", methods=["POST"])
def reissue_element(element_id):
    require("StoreAssociate")
    element = get_element(element_id)
    if element["status"] not in ("CATALOG", "RETIRED_TO_ARCHIVE"):
        fail("ERR_INVALID_STATE", "Only an archived element may be reissued.")
    element["status"] = "ACTIVE"
    element["sourcing_mode"] = "CURRENT_PRODUCTION"
    touch(element)
    return envelope(out(element))