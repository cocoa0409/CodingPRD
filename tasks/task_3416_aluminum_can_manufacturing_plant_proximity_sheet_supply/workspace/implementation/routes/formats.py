"""Can format endpoints: propose, get, list, tool, qualify, retire."""
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch
from errors import (ApiError, ERR_NOT_FOUND, ERR_CUSTOMER_NOT_FOUND,
                    ERR_INVALID_STATE, ERR_FORMAT_HAS_OPEN_RUNS,
                    ERR_TOOLING_TERMS_REQUIRED)
from middleware import actor, require_role
from response import ok_object, ok_list
from routes.plants import get_plant_or_404
from services import calc
from services.serialize import format_public
from validation import (body_json, req_str, req_int, req_num, req_bool,
                        req_enum, pagination_args)

bp = Blueprint("formats", __name__)

SHAPES = ("STANDARD", "SLEEK", "SLIM", "STUBBY")


def get_format_or_404(fid):
    fmt = store["formats"].get(fid)
    if fmt is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Can format not found.")
    return fmt


@bp.post("/plants/<pid>/formats")
def create_format(pid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    data = body_json()
    customer_id = req_str(data, "customer_id")
    size_code = req_str(data, "size_code")
    shape = req_enum(data, "shape", SHAPES)
    is_specialty = req_bool(data, "is_specialty")
    metal_lbs = req_num(data, "metal_lbs_per_1000_units", gt=0)
    tooling = req_int(data, "tooling_investment_cents", minimum=0)
    min_vol = req_int(data, "min_volume_commitment_units", minimum=0)
    plant = get_plant_or_404(pid)
    if store["customers"].get(customer_id) is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND[0], ERR_CUSTOMER_NOT_FOUND[1],
                       "customer_id does not match an existing customer.")
    ts = now_iso()
    fmt = {
        "id": new_id(),
        "plant_id": plant["id"],
        "customer_id": customer_id,
        "size_code": size_code,
        "shape": shape,
        "is_specialty": is_specialty,
        "metal_lbs_per_1000_units": metal_lbs,
        "tooling_investment_cents": tooling,
        "min_volume_commitment_units": min_vol,
        "status": "PROPOSED",
        "delivered_units": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["formats"][fmt["id"]] = fmt
    return ok_object(format_public(fmt), code=201)


@bp.get("/formats/<fid>")
def get_format(fid):
    actor()
    return ok_object(format_public(get_format_or_404(fid)))


@bp.get("/formats")
def list_formats():
    actor()
    limit, offset = pagination_args()
    plant_id = request.args.get("plant_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = sorted(store["formats"].values(), key=lambda f: f["_created_sort"])
    if plant_id is not None:
        items = [f for f in items if f["plant_id"] == plant_id]
    if customer_id is not None:
        items = [f for f in items if f["customer_id"] == customer_id]
    if status is not None:
        items = [f for f in items if f["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([format_public(f) for f in page], limit, offset, total)


@bp.post("/formats/<fid>/tool")
def tool_format(fid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    fmt = get_format_or_404(fid)
    if fmt["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a PROPOSED format can be tooled.")
    if fmt["is_specialty"] and not (
        fmt["tooling_investment_cents"] > 0 and fmt["min_volume_commitment_units"] > 0
    ):
        raise ApiError(ERR_TOOLING_TERMS_REQUIRED[0], ERR_TOOLING_TERMS_REQUIRED[1],
                       "Specialty format tooling requires tooling_investment_cents > 0 "
                       "and min_volume_commitment_units > 0.")
    fmt["status"] = "TOOLED"
    touch(fmt)
    return ok_object(format_public(fmt))


@bp.post("/formats/<fid>/qualify")
def qualify_format(fid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    fmt = get_format_or_404(fid)
    if fmt["status"] != "TOOLED":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a TOOLED format can be qualified.")
    fmt["status"] = "QUALIFIED"
    touch(fmt)
    return ok_object(format_public(fmt))


@bp.post("/formats/<fid>/retire")
def retire_format(fid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    fmt = get_format_or_404(fid)
    if fmt["status"] not in ("TOOLED", "QUALIFIED"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a TOOLED or QUALIFIED format can be retired.")
    for r in store["runs"].values():
        if r["format_id"] == fmt["id"] and r["status"] in calc.OPEN_RUN_STATUSES:
            raise ApiError(ERR_FORMAT_HAS_OPEN_RUNS[0], ERR_FORMAT_HAS_OPEN_RUNS[1],
                           "Format has runs in SCHEDULED, IN_PROGRESS, or HELD.")
    fmt["status"] = "RETIRED"
    touch(fmt)
    return ok_object(format_public(fmt))
