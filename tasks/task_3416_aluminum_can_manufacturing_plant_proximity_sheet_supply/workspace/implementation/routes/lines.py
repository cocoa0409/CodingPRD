"""Production line endpoints (nested under plants)."""
from flask import Blueprint

from db import store, new_id, now_iso, next_seq
from middleware import actor, require_role
from response import ok_object, ok_list
from routes.plants import get_plant_or_404
from services.serialize import line_public
from validation import body_json, req_str, req_int, req_num, pagination_args

bp = Blueprint("lines", __name__)


@bp.post("/plants/<pid>/lines")
def create_line(pid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    data = body_json()
    name = req_str(data, "name")
    speed = req_int(data, "nominal_speed_cans_per_hour", minimum=1)
    base_spoilage = req_num(data, "base_spoilage_pct", gte=0, lt=1)
    plant = get_plant_or_404(pid)
    ts = now_iso()
    line = {
        "id": new_id(),
        "plant_id": plant["id"],
        "name": name,
        "nominal_speed_cans_per_hour": speed,
        "base_spoilage_pct": base_spoilage,
        "operational_status": "RUNNING",
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["lines"][line["id"]] = line
    return ok_object(line_public(line), code=201)


@bp.get("/plants/<pid>/lines")
def list_lines(pid):
    actor()
    plant = get_plant_or_404(pid)
    limit, offset = pagination_args()
    items = sorted(
        (l for l in store["lines"].values() if l["plant_id"] == plant["id"]),
        key=lambda l: l["_created_sort"],
    )
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([line_public(l) for l in page], limit, offset, total)
