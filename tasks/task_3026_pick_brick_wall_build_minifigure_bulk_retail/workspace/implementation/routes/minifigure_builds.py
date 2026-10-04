"""Build-a-Minifigure: the assembly platform, component placement and sealing."""

from flask import Blueprint

from db import MINIFIGURE_SEAL_POINTS, SEALED_CORRECTION_HOURS, db, hours_later
from errors import fail
from middleware import require, require_owner
from response import envelope, paginate
from services.core import get_build, get_member, get_store, new_record, touch
from services.wall import element_on_wall
from utils import body, list_params, matches, out, require_fields

bp = Blueprint("minifigure_builds", __name__)

SLOTS = ("torso_element_id", "head_element_id", "legs_element_id", "accessory_element_id")

# The sealing instant is bookkeeping only -- it is not part of the declared
# resource shape, so it is kept beside the record rather than on it.
SEALED_AT = {}


def compute_missing(build):
    """minifigure_component_availability -- a null accessory is not missing."""
    store_id = build["store_id"]
    missing = 0
    for slot in SLOTS:
        element_id = build.get(slot)
        if element_id is None:
            continue
        if not element_on_wall(store_id, element_id):
            missing += 1
    build["components_missing"] = missing
    return build


@bp.route("/stores/minifigure-builds", methods=["POST"])
def open_build():
    require("StoreAssociate")
    payload = body()
    require_fields(payload, "store_id", "member_id")
    store = get_store(payload["store_id"])
    member = get_member(payload["member_id"])

    build = new_record({
        "store_id": store["id"],
        "member_id": member["id"],
        "torso_element_id": None,
        "head_element_id": None,
        "legs_element_id": None,
        "accessory_element_id": None,
        "platform_gen": 0,
        "components_missing": 4,
        "status": "BUILDING",
    })
    db().minifigure_builds[build["id"]] = build
    return envelope(out(build), status=201)


@bp.route("/stores/minifigure-builds", methods=["GET"])
def list_builds():
    require("StoreAssociate", "Member")
    params = list_params()
    items = [b for b in db().minifigure_builds.values()
             if matches(b, params, "store_id", "member_id", "status",
                        "torso_element_id", "head_element_id",
                        "legs_element_id", "accessory_element_id")]
    items.sort(key=lambda b: (b["created_at"], b["id"]))
    page, pagination = paginate(items, params)
    return envelope(out(page), response_type="array", pagination=pagination)


@bp.route("/stores/minifigure-builds/<build_id>", methods=["GET"])
def read_build(build_id):
    require("Member", "StoreAssociate")
    return envelope(out(get_build(build_id)))


@bp.route("/stores/minifigure-builds/<build_id>/components", methods=["POST"])
def place_components(build_id):
    payload = body()
    build = get_build(build_id)
    require_owner(build["member_id"])
    require("Member")

    if build["status"] == "RETURNED":
        fail("ERR_INVALID_STATE", "A returned build is terminal.")
    if build["status"] == "SEALED":
        from db import now
        sealed_at = SEALED_AT.get(build["id"]) or now()
        if now() > hours_later(sealed_at, SEALED_CORRECTION_HOURS):
            fail("ERR_INVALID_STATE",
                 "The correction hold on this sealed figure has expired.")

    supplied = {slot: payload[slot] for slot in SLOTS if slot in payload}

    # Every named element must be physically on the wall of this store.
    for slot, element_id in supplied.items():
        if element_id is None:
            continue
        element = db().elements.get(element_id)
        if element is None:
            fail("ERR_NOT_FOUND", "No element exists with id %s." % element_id)
        if not element_on_wall(build["store_id"], element_id):
            fail("ERR_COMPONENT_NOT_STOCKED",
                 "The element is not loaded in any bin of this store holding mass.")

    for slot, element_id in supplied.items():
        build[slot] = element_id

    build["status"] = "BUILDING"
    build["platform_gen"] += 1
    compute_missing(build)
    touch(build)
    return envelope(out(build))


@bp.route("/stores/minifigure-builds/<build_id>/seal", methods=["POST"])
def seal_build(build_id):
    payload = body()
    build = get_build(build_id)
    require_owner(build["member_id"])
    require("Member")

    expected = payload.get("expected_build_version")
    if expected is not None and int(expected) != build["version"]:
        fail("ERR_STALE_VERSION",
             "expected_build_version no longer matches the build's version.")

    if build["status"] != "BUILDING":
        fail("ERR_INVALID_STATE", "Only a build in progress may be sealed.")

    compute_missing(build)
    if build["components_missing"] > 0:
        fail("ERR_COMPONENTS_INCOMPLETE",
             "Every component slot must be stocked before the figure can be sealed.")
    if build["platform_gen"] < 1:
        fail("ERR_COMPONENTS_INCOMPLETE",
             "The assembly platform must be populated at least once before sealing.")

    member = get_member(build["member_id"])
    build["status"] = "SEALED"
    from db import now
    SEALED_AT[build["id"]] = now()
    touch(build)
    member["points_balance"] += MINIFIGURE_SEAL_POINTS
    touch(member)
    return envelope(out(build))