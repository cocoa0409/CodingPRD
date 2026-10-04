"""LocalizationAgreement routes."""
from flask import Blueprint, request

from db import db
from errors import (err_not_found, err_invalid_state, err_invalid_request,
                    err_unknown_action, ApiError)
from middleware import require_auth, ANY_ROLE
from clock import now_dt
from response import success_obj
from routes_common import stamp_new, touch, serialize, paginate
from util import body_of, req_str, req_int, req_num, req_dt

bp = Blueprint("localizations", __name__)

ACTIVE_FREIGHT = {"BOOKED", "IN_TRANSIT", "CUSTOMS_HOLD", "DUTY_ASSESSED", "CLEARED"}


@bp.route("/localization-agreements", methods=["POST"])
def create_agreement():
    require_auth({"LocalizationPartner", "PlatformAdmin"})
    data = body_of(request)
    campaign_id = data.get("campaign_id")
    if not isinstance(campaign_id, str):
        raise err_invalid_request("campaign_id is required")
    campaign = db.campaigns.get(campaign_id)
    if not campaign:
        raise err_not_found("campaign not found")
    partner_name = req_str(data, "partner_name")
    language_code = req_str(data, "language_code")
    royalty = req_num(data, "royalty_pct")
    if not (0 < float(royalty) < 0.25):
        raise err_invalid_request("royalty_pct must be in (0, 0.25)")
    units = req_int(data, "print_commitment_units", minimum=0)
    pws = req_dt(data, "print_window_start")
    pwe = req_dt(data, "print_window_end")
    if not (pwe > pws):
        raise err_invalid_request("print_window_end must be after print_window_start")
    for la in db.localizations.values():
        if la["campaign_id"] == campaign_id and la["language_code"] == language_code:
            raise err_invalid_request("language_code must be unique per campaign")

    agreement = {
        "campaign_id": campaign_id,
        "partner_name": partner_name,
        "language_code": language_code,
        "royalty_pct": royalty,
        "print_commitment_units": units,
        "print_window_start": pws,
        "print_window_end": pwe,
        "status": "NEGOTIATING",
    }
    stamp_new(agreement)
    db.localizations[agreement["id"]] = agreement
    return success_obj(serialize(agreement), 201)


@bp.route("/localization-agreements/<lid>", methods=["GET"])
def get_agreement(lid):
    require_auth(ANY_ROLE)
    a = db.localizations.get(lid)
    if not a:
        raise err_not_found("agreement not found")
    return success_obj(serialize(a))


@bp.route("/localization-agreements", methods=["GET"])
def list_agreements():
    require_auth(ANY_ROLE)
    items = list(db.localizations.values())
    args = request.args
    if args.get("campaign_id"):
        items = [a for a in items if a["campaign_id"] == args["campaign_id"]]
    if args.get("status"):
        items = [a for a in items if a["status"] == args["status"]]
    return paginate(items)


@bp.route("/localization-agreements/<lid>/transition", methods=["POST"])
def agreement_transition(lid):
    require_auth({"LocalizationPartner"})
    a = db.localizations.get(lid)
    if not a:
        raise err_not_found("agreement not found")
    data = body_of(request)
    action = data.get("action")
    if not isinstance(action, str):
        raise err_invalid_request("action is required")
    if action not in ("sign", "renegotiate", "mark-printed", "terminate"):
        raise err_unknown_action(f"unknown action {action}")
    campaign = db.campaigns.get(a["campaign_id"])
    now = now_dt()

    if action == "sign":
        if a["status"] != "NEGOTIATING":
            raise err_invalid_state("sign requires NEGOTIATING")
        for s in db.freight_shipments.values():
            run = db.production_runs.get(s["production_run_id"])
            if not run or run["campaign_id"] != a["campaign_id"]:
                continue
            if s["status"] not in ACTIVE_FREIGHT:
                continue
            if a["print_window_start"] < s["arrives_at"] and s["departs_at"] < a["print_window_end"]:
                raise ApiError("ERR_PRINT_WINDOW_OVERLAP", 409,
                               "print window overlaps active freight sailing window")
        a["status"] = "SIGNED"
        touch(a)
        if campaign:
            touch(campaign)

    elif action == "renegotiate":
        if a["status"] != "SIGNED":
            raise err_invalid_state("renegotiate requires SIGNED")
        if campaign["status"] not in ("CLOSED_SUCCESS", "IN_PRODUCTION"):
            raise ApiError("ERR_CAMPAIGN_NOT_READY", 409, "campaign not renegotiable")
        a["status"] = "NEGOTIATING"
        touch(a)

    elif action == "mark-printed":
        if a["status"] != "SIGNED":
            raise err_invalid_state("mark-printed requires SIGNED")
        if not (a["print_window_start"] <= now < a["print_window_end"]):
            raise ApiError("ERR_PRINT_WINDOW_NOT_OPEN", 409, "print window not open")
        a["status"] = "PRINTED"
        touch(a)

    elif action == "terminate":
        if a["status"] != "NEGOTIATING":
            raise err_invalid_state("terminate requires NEGOTIATING")
        a["status"] = "TERMINATED"
        touch(a)

    return success_obj(serialize(a))
