"""BuildKit — touring hardware: condition decay, the twice-only refurbishment
fork and the localisation cost (PRD §3.8)."""

from flask import Blueprint, request

from db import db, new_row, public, touch
from errors import ApiError
from middleware import EP, LM, VOM, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body

bp = Blueprint("kits", __name__)

KIT_CODE_PATTERN = r"^[A-Z0-9\-]+$"


@bp.post("/build-kits")
@roles(VOM)
def register_kit():
    body = Body(require_body=True)
    kit_code = body.string("kit_code", min_len=1, max_len=40,
                           pattern=KIT_CODE_PATTERN)
    origin_run_id = body.reference("origin_run_id", required=False, default=None)
    module_count = body.integer("module_count", minimum=1, maximum=60)
    language = body.string("localization_language", min_len=2, max_len=12)
    initial = body.number("initial_condition_score", required=False,
                          default=100.00, minimum=0, maximum=100)

    # rung 5 — the optional provenance link must resolve when supplied
    origin_run = None
    if origin_run_id is not None:
        origin_run = derive.run(origin_run_id)
    # rung 6 — uniqueness
    for peer in db.kits.values():
        if peer["kit_code"] == kit_code:
            raise ApiError("ERR_DUPLICATE_KIT_CODE")

    score = calc.two_dp(initial)
    row = new_row()
    row.update({
        "kit_code": kit_code,
        "origin_run_id": origin_run["id"] if origin_run is not None else None,
        "module_count": module_count,
        "initial_condition_score": float(score),
        "condition_score": float(score),
        "reuse_cycle_count": 0,
        "refurb_count": 0,
        "last_city_code": None,
        "localization_language": language,
        "localization_cost_cents": 0,
        # fabricated already localised for its first city
        "localization_status": "LOCALIZED",
        "status": "READY",
    })
    db.kits[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/build-kits/<kit_id>")
@roles(VOM, EP, LM)
def read_kit(kit_id):
    return object_response(public(derive.kit(kit_id)))


@bp.get("/build-kits")
@roles(VOM, EP, LM)
def list_kits():
    rows = list(db.kits.values())
    for field in ("origin_run_id", "status", "localization_status"):
        value = request.args.get(field)
        if value:
            rows = [r for r in rows if r[field] == value]
    return list_response(rows)


@bp.post("/build-kits/<kit_id>/refurbish")
@roles(VOM)
def refurbish_kit(kit_id):
    kit_row = derive.kit(kit_id)
    body = Body()
    body.string("note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state
    if kit_row["status"] != "REFURB_REQUIRED":
        raise ApiError("ERR_KIT_INVALID_STATE")

    # one trigger, two targets, selected by the counter
    if kit_row["refurb_count"] >= calc.REFURB_CAP:
        # the allowance is spent: the kit is retired exactly as it stands
        kit_row["status"] = "RETIRED"
    else:
        restored = min(calc.dec("100.00"),
                       calc.dec(kit_row["condition_score"]) + calc.REFURB_GAIN)
        kit_row["condition_score"] = float(calc.two_dp(restored))
        kit_row["refurb_count"] += 1
        # localisation stays PENDING and reuse_cycle_count is not cleared, so
        # the localisation discount keeps accruing across rebuilds
        kit_row["status"] = "IN_TRANSIT"
    touch(kit_row)
    return object_response(public(kit_row))


@bp.post("/build-kits/<kit_id>/localize")
@roles(VOM)
def localize_kit(kit_id):
    kit_row = derive.kit(kit_id)
    body = Body(require_body=True)
    language = body.string("localization_language", min_len=2, max_len=12)

    # rung 8 — own state
    if kit_row["status"] != "IN_TRANSIT":
        raise ApiError("ERR_KIT_INVALID_STATE")
    if kit_row["localization_status"] != "PENDING":
        raise ApiError("ERR_KIT_INVALID_STATE")
    # rung 16 — a worn kit is not worth localising
    if calc.dec(kit_row["condition_score"]) < calc.KIT_CONDITION_RUN_MIN:
        raise ApiError("ERR_KIT_CONDITION_BELOW_THRESHOLD")

    kit_row["localization_language"] = language
    kit_row["localization_cost_cents"] = calc.kit_localization_cost_cents(
        kit_row["module_count"], kit_row["reuse_cycle_count"])
    kit_row["localization_status"] = "LOCALIZED"
    kit_row["status"] = "READY"
    touch(kit_row)
    return object_response(public(kit_row))
