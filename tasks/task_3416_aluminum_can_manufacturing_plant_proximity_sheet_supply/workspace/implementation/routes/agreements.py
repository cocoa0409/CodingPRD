"""Supply agreement lifecycle: create, list, get, sign, renegotiate, amend,
terminate. OCC on expected_agreement_version for amend (gate 5)."""
from flask import Blueprint, request

from db import store, new_id, now_iso, next_seq, touch, clock_date_str
from errors import (ApiError, ERR_NOT_FOUND, ERR_PLANT_NOT_FOUND,
                    ERR_CUSTOMER_NOT_FOUND, ERR_VALIDATION, ERR_STALE_VERSION,
                    ERR_INVALID_STATE, ERR_AGREEMENT_WINDOW_PASSED)
from middleware import actor, require_role, require_customer_owner
from response import ok_object, ok_list
from services import calc
from services.serialize import agreement_public
from validation import (body_json, req_str, req_int, opt_int, req_num, opt_num,
                        opt_str, parse_date, pagination_args)

bp = Blueprint("agreements", __name__)


def _get_agreement_or_none(aid):
    return store["agreements"].get(aid)


def _get_agreement(aid):
    agr = store["agreements"].get(aid)
    if agr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    return agr


@bp.post("/supply-agreements")
def create_agreement():
    _, role = actor()
    require_role(role, ["PlantManager"])
    data = body_json()
    plant_id = req_str(data, "plant_id")
    customer_id = req_str(data, "customer_id")
    committed = req_int(data, "committed_annual_units", minimum=calc.MIN_COMMITTED_ANNUAL_UNITS)
    ptp = req_num(data, "pass_through_pct", gt=0, lte=1)
    conv = req_num(data, "conversion_cost_cents_per_1000", gt=0)
    start_date = parse_date(req_str(data, "start_date"), "start_date")
    end_date = parse_date(req_str(data, "end_date"), "end_date")
    if end_date <= start_date:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "end_date must be strictly after start_date.")
    plant = store["plants"].get(plant_id)
    if plant is None:
        raise ApiError(ERR_PLANT_NOT_FOUND[0], ERR_PLANT_NOT_FOUND[1],
                       "plant_id does not match an existing plant.")
    customer = store["customers"].get(customer_id)
    if customer is None:
        raise ApiError(ERR_CUSTOMER_NOT_FOUND[0], ERR_CUSTOMER_NOT_FOUND[1],
                       "customer_id does not match an existing customer.")
    if plant["region"] == customer["home_region"]:
        freight_zone = "NEAR"
    elif plant["region"][:2] == customer["home_region"][:2]:
        freight_zone = "MID"
    else:
        freight_zone = "FAR"
    ts = now_iso()
    agr = {
        "id": new_id(),
        "plant_id": plant_id,
        "customer_id": customer_id,
        "freight_zone": freight_zone,
        "committed_annual_units": committed,
        "pass_through_pct": ptp,
        "conversion_cost_cents_per_1000": conv,
        "start_date": start_date,
        "end_date": end_date,
        "status": "DRAFT",
        "ytd_settled_units": 0,
        "delivered_revenue_cents": 0,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_created_sort": next_seq(),
    }
    store["agreements"][agr["id"]] = agr
    return ok_object(agreement_public(agr), code=201)


@bp.get("/supply-agreements")
def list_agreements():
    actor()
    limit, offset = pagination_args()
    plant_id = request.args.get("plant_id")
    customer_id = request.args.get("customer_id")
    status = request.args.get("status")
    items = sorted(store["agreements"].values(), key=lambda a: a["_created_sort"])
    if plant_id is not None:
        items = [a for a in items if a["plant_id"] == plant_id]
    if customer_id is not None:
        items = [a for a in items if a["customer_id"] == customer_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    total = len(items)
    page = items[offset:offset + limit]
    return ok_list([agreement_public(a) for a in page], limit, offset, total)


@bp.get("/supply-agreements/<aid>")
def get_agreement(aid):
    actor()
    return ok_object(agreement_public(_get_agreement(aid)))


@bp.post("/supply-agreements/<aid>/sign")
def sign_agreement(aid):
    user_id, role = actor()
    require_role(role, ["CustomerPlanner"])
    agr = _get_agreement_or_none(aid)
    if agr is not None:
        require_customer_owner(user_id, agr["customer_id"])
    if agr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    if agr["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a DRAFT agreement can be signed.")
    if clock_date_str() > agr["end_date"]:
        raise ApiError(ERR_AGREEMENT_WINDOW_PASSED[0], ERR_AGREEMENT_WINDOW_PASSED[1],
                       "The logical clock date is past the agreement end_date.")
    agr["status"] = "ACTIVE"
    touch(agr)
    return ok_object(agreement_public(agr))


@bp.post("/supply-agreements/<aid>/open-renegotiation")
def open_renegotiation(aid):
    user_id, role = actor()
    require_role(role, ["CustomerPlanner"])
    agr = _get_agreement_or_none(aid)
    if agr is not None:
        require_customer_owner(user_id, agr["customer_id"])
    if agr is None:
        raise ApiError(ERR_NOT_FOUND[0], ERR_NOT_FOUND[1], "Supply agreement not found.")
    if agr["status"] != "ACTIVE":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an ACTIVE agreement can be reopened for renegotiation.")
    agr["status"] = "RENEGOTIATING"
    touch(agr)
    return ok_object(agreement_public(agr))


@bp.post("/supply-agreements/<aid>/amend")
def amend_agreement(aid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    data = body_json()
    expected_version = req_int(data, "expected_agreement_version")
    committed = opt_int(data, "committed_annual_units", minimum=calc.MIN_COMMITTED_ANNUAL_UNITS)
    ptp = opt_num(data, "pass_through_pct", gt=0, lte=1)
    conv = opt_num(data, "conversion_cost_cents_per_1000", gt=0)
    end_date_raw = opt_str(data, "end_date")
    end_date = parse_date(end_date_raw, "end_date") if end_date_raw is not None else None
    agr = _get_agreement(aid)
    if end_date is not None and end_date <= agr["start_date"]:
        raise ApiError(ERR_VALIDATION[0], ERR_VALIDATION[1],
                       "end_date must be strictly after start_date.")
    if expected_version != agr["version"]:
        raise ApiError(ERR_STALE_VERSION[0], ERR_STALE_VERSION[1],
                       "expected_agreement_version does not match the current agreement version.")
    if agr["status"] != "RENEGOTIATING":
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only a RENEGOTIATING agreement can be amended.")
    if committed is not None:
        agr["committed_annual_units"] = committed
    if ptp is not None:
        agr["pass_through_pct"] = ptp
    if conv is not None:
        agr["conversion_cost_cents_per_1000"] = conv
    if end_date is not None:
        agr["end_date"] = end_date
    agr["status"] = "ACTIVE"
    touch(agr)
    return ok_object(agreement_public(agr))


@bp.post("/supply-agreements/<aid>/terminate")
def terminate_agreement(aid):
    _, role = actor()
    require_role(role, ["PlantManager"])
    agr = _get_agreement(aid)
    if agr["status"] not in ("ACTIVE", "RENEGOTIATING"):
        raise ApiError(ERR_INVALID_STATE[0], ERR_INVALID_STATE[1],
                       "Only an ACTIVE or RENEGOTIATING agreement can be terminated.")
    exposure = calc.early_termination_exposure(agr)
    agr["status"] = "TERMINATED"
    touch(agr)
    return ok_object(exposure)
