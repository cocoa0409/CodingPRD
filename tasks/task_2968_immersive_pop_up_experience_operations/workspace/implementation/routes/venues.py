"""PopupVenue — lease term, permit rounds and buildout funding (PRD §3.1)."""

from flask import Blueprint, request

from db import db, iso, new_row, now, now_iso, public, today, touch
from errors import ApiError
from middleware import EP, GSA, LM, SO, VOM, caller_id, roles
from response import list_response, object_response
from services import calc, derive
from services.validate import Body, fail

bp = Blueprint("venues", __name__)

VENUE_STATUSES = ("DRAFT", "PERMIT_UNDER_REVIEW", "PERMIT_CONDITIONS",
                  "PERMIT_ISSUED", "PERMIT_DENIED", "LEASE_ACTIVE", "LEASE_ENDED")
PERMIT_DECISIONS = ("ISSUED", "CONDITIONS", "DENIED")
PERMIT_ROUND_CAP = 3
ACTIVE_RUN_STATUSES = ("PLANNED", "OPEN", "EXTENDED", "CLOSING")


@bp.post("/venues")
@roles(VOM)
def register_venue():
    body = Body(require_body=True)
    city_code = body.string("city_code", min_len=3, max_len=3, pattern=r"^[A-Z]{3}$")
    site_name = body.string("site_name", min_len=1, max_len=120)
    lease_start, lease_start_raw = body.date_field("lease_start_date")
    lease_end, lease_end_raw = body.date_field("lease_end_date")
    option_days = body.integer("lease_extension_option_days", required=False,
                               default=0, minimum=0, maximum=180)
    base_rent = body.integer("base_monthly_rent_cents", minimum=0)
    allowance = body.integer("buildout_allowance_cents", minimum=0)
    kit_credit = body.integer("kit_reuse_credit_cents", required=False, default=0,
                              minimum=0)
    cap = body.integer("buildout_cap_cents", minimum=0)
    requested_load = body.integer("requested_occupancy_load", minimum=1)
    egress_width = body.number("egress_width_cm", exclusive_minimum=0)
    sprinklered = body.boolean("sprinklered", required=False, default=False)

    if cap < allowance:
        fail("buildout_cap_cents may never be below buildout_allowance_cents.")

    # rung 11 — interval bounds
    if lease_end <= lease_start:
        raise ApiError("ERR_INVALID_WINDOW")

    row = new_row()
    row.update({
        "city_code": city_code,
        "site_name": site_name,
        "lease_start_date": lease_start_raw,
        "lease_end_date": lease_end_raw,
        "lease_extension_option_days": option_days,
        "lease_extension_days_consumed": 0,
        "base_monthly_rent_cents": base_rent,
        "buildout_allowance_cents": allowance,
        "kit_reuse_credit_cents": kit_credit,
        "buildout_cap_cents": cap,
        "allowance_drawn_cents": 0,
        "kit_credit_drawn_cents": 0,
        "operator_capex_cents": 0,
        "buildout_spend_cents": 0,
        "requested_occupancy_load": requested_load,
        "permitted_occupancy_load": 0,
        "egress_width_cm": egress_width,
        "egress_capacity": calc.egress_capacity(egress_width),
        "sprinklered": sprinklered,
        "permit_submission_round": 0,
        "permit_conditions_note": None,
        "permit_denial_reason": None,
        "permit_issued_at": None,
        "lease_activated_at": None,
        "status": "DRAFT",
        "_lease_start": lease_start,
        "_lease_end": lease_end,
    })
    db.venues[row["id"]] = row
    return object_response(public(row), 201)


@bp.get("/venues/<venue_id>")
@roles(VOM, LM, EP, SO, GSA)
def read_venue(venue_id):
    return object_response(public(derive.venue(venue_id)))


@bp.get("/venues")
@roles(VOM, LM, EP, SO)
def list_venues():
    rows = list(db.venues.values())
    city_code = request.args.get("city_code")
    if city_code:
        rows = [r for r in rows if r["city_code"] == city_code]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows)


@bp.post("/venues/<venue_id>/permit-submissions")
@roles(VOM)
def submit_permit(venue_id):
    venue = derive.venue(venue_id)
    body = Body()
    body.string("package_note", required=False, default=None, min_len=1, max_len=500)

    # rung 8 — own state
    if venue["status"] not in ("DRAFT", "PERMIT_CONDITIONS"):
        raise ApiError("ERR_VENUE_INVALID_STATE")
    # rung 15 — capacity ceiling
    if venue["requested_occupancy_load"] > venue["egress_capacity"]:
        raise ApiError("ERR_OCCUPANCY_ABOVE_EGRESS")
    # rung 16 — loop cap
    if venue["permit_submission_round"] >= PERMIT_ROUND_CAP:
        raise ApiError("ERR_PERMIT_ROUND_CAP")

    venue["status"] = "PERMIT_UNDER_REVIEW"
    venue["permit_submission_round"] += 1
    venue["permit_conditions_note"] = None
    touch(venue)
    return object_response(public(venue))


@bp.post("/venues/<venue_id>/permit-decisions")
@roles(SO)
def decide_permit(venue_id):
    venue = derive.venue(venue_id)
    body = Body(require_body=True)
    decision = body.enum("decision", PERMIT_DECISIONS)
    note = body.string("note", required=False, default=None, min_len=1, max_len=500)
    if decision in ("CONDITIONS", "DENIED") and note is None:
        fail("Field 'note' is required on a %s decision." % decision)

    if venue["status"] != "PERMIT_UNDER_REVIEW":
        raise ApiError("ERR_VENUE_INVALID_STATE")

    if decision == "ISSUED":
        venue["status"] = "PERMIT_ISSUED"
        venue["permit_issued_at"] = now_iso()
        venue["permit_conditions_note"] = None
        venue["permitted_occupancy_load"] = min(venue["requested_occupancy_load"],
                                                venue["egress_capacity"])
    elif decision == "CONDITIONS":
        venue["status"] = "PERMIT_CONDITIONS"
        venue["permit_conditions_note"] = note
        venue["permitted_occupancy_load"] = 0
    else:
        venue["status"] = "PERMIT_DENIED"
        venue["permit_denial_reason"] = note
        venue["permitted_occupancy_load"] = 0
    touch(venue)
    return object_response(public(venue))


@bp.post("/venues/<venue_id>/activate-lease")
@roles(VOM)
def activate_lease(venue_id):
    venue = derive.venue(venue_id)
    if venue["status"] != "PERMIT_ISSUED":
        raise ApiError("ERR_VENUE_INVALID_STATE")
    # rung 12 — clock position
    if today() < venue["_lease_start"]:
        raise ApiError("ERR_LEASE_START_NOT_REACHED")
    venue["status"] = "LEASE_ACTIVE"
    venue["lease_activated_at"] = now_iso()
    touch(venue)
    return object_response(public(venue))


@bp.post("/venues/<venue_id>/end-lease")
@roles(VOM)
def end_lease(venue_id):
    venue = derive.venue(venue_id)
    if venue["status"] != "LEASE_ACTIVE":
        raise ApiError("ERR_VENUE_INVALID_STATE")
    for run_row in derive.runs_of_venue(venue):
        if run_row["run_status"] in ACTIVE_RUN_STATUSES:
            raise ApiError("ERR_VENUE_HAS_ACTIVE_RUN")
    venue["status"] = "LEASE_ENDED"
    touch(venue)
    return object_response(public(venue))


@bp.post("/venues/<venue_id>/buildout-draws")
@roles(VOM)
def buildout_draw(venue_id):
    venue = derive.venue(venue_id)
    body = Body(require_body=True)
    draw = body.integer("draw_amount_cents", minimum=0)
    body.string("memo", required=False, default=None, min_len=1, max_len=500)

    if venue["status"] in ("PERMIT_DENIED", "LEASE_ENDED"):
        raise ApiError("ERR_VENUE_INVALID_STATE")

    # rung 17 — the ceiling is checked before any bucket is touched
    if venue["buildout_spend_cents"] + draw > venue["buildout_cap_cents"]:
        raise ApiError("ERR_BUILDOUT_CAP_EXCEEDED")

    remaining = draw
    take1 = min(remaining, venue["buildout_allowance_cents"] - venue["allowance_drawn_cents"])
    venue["allowance_drawn_cents"] += take1
    remaining -= take1
    take2 = min(remaining, venue["kit_reuse_credit_cents"] - venue["kit_credit_drawn_cents"])
    venue["kit_credit_drawn_cents"] += take2
    remaining -= take2
    venue["operator_capex_cents"] += remaining
    venue["buildout_spend_cents"] += draw
    touch(venue)
    return object_response(public(venue))
