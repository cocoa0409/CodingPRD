"""Subscription commitments and cost-share agreement routes."""
from flask import Blueprint, request

from calc import (escalate_reallocate, recompute_csa_allocated,
                  recompute_dca_subscription_fields, withdrawal_penalty)
from errors import (ApiError, ERR_CAPACITY_EXCEEDED, ERR_DUPLICATE,
                    ERR_ESCALATION_OUT_OF_RANGE, ERR_INVALID_STATE,
                    ERR_STALE_VERSION, ERR_UNAUTHORIZED)
from rbac import get_user_id, require_role
from store import (DB, apply_pagination, base_record, get_clock, paginate_args,
                   parse_iso, serialize, sort_by_created, success_list,
                   success_object, touch)
from validation import get_or_404, json_body, v_int, v_num, v_str

bp = Blueprint("subscriptions", __name__, url_prefix="/licensing")


def _invalid(msg):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def _own_sub(sub):
    """UtilityParticipant ownership: X-User-ID must equal the commitment's utility_id."""
    if get_user_id() != sub["utility_id"]:
        raise ApiError(ERR_UNAUTHORIZED, 403, "utility may act only on its own commitments")


@bp.post("/dcas/<dca_id>/subscriptions")
def create_subscription(dca_id):
    user_id, _ = require_role("UtilityParticipant")
    get_or_404("dca", dca_id)
    body = json_body()
    utility_id = v_str(body, "utility_id")
    if utility_id != user_id:
        raise ApiError(ERR_UNAUTHORIZED, 403, "utility_id must match the acting utility")
    committed = v_int(body, "committed_mw", minimum=1)
    price = v_num(body, "price_per_mwh_usd", minimum=0, exclusive_min=True)
    for s in DB["subscription"].values():
        if s["dca_id"] == dca_id and s["utility_id"] == utility_id:
            raise ApiError(ERR_DUPLICATE, 409, "commitment already exists for this application-utility pair")
    sub = base_record("subscription", {
        "dca_id": dca_id,
        "utility_id": utility_id,
        "committed_mw": committed,
        "price_per_mwh_usd": price,
        "status": "DRAFT",
        "cost_share_total_usd": 0,
        "allocated_overrun_usd": 0,
        "withdrawal_reserve_usd": 0,
        "offload_penalty_usd": 0,
        "executed_at": None,
    })
    DB["subscription"][sub["id"]] = sub
    return success_object(serialize(sub), status=201)


@bp.get("/subscriptions")
def list_subscriptions():
    require_role()
    items = list(DB["subscription"].values())
    for param in ("dca_id", "utility_id", "status"):
        val = request.args.get(param)
        if val is not None:
            items = [s for s in items if s[param] == val]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(s) for s in page], total, limit, offset)


@bp.get("/subscriptions/<id>")
def get_subscription(id):
    require_role()
    return success_object(serialize(get_or_404("subscription", id)))


@bp.post("/subscriptions/<id>/execute")
def execute_subscription(id):
    require_role("UtilityParticipant")
    sub = get_or_404("subscription", id)
    _own_sub(sub)
    if sub["status"] != "DRAFT":
        raise _invalid("commitment is not DRAFT")
    dca = get_or_404("dca", sub["dca_id"])
    if dca["status"] not in ("SUBMITTED", "SAFETY_REVIEW", "ADVANCED_REVIEW"):
        raise _invalid("application is not open for subscription execution")
    recompute_dca_subscription_fields(sub["dca_id"])
    if sub["committed_mw"] > dca["available_mw"]:
        raise ApiError(ERR_CAPACITY_EXCEEDED, 422,
                       "committed_mw exceeds available_mw")
    from store import now_iso_ms
    sub["status"] = "EXECUTED"
    sub["executed_at"] = now_iso_ms()
    touch(sub)
    recompute_dca_subscription_fields(sub["dca_id"])
    touch(dca)
    return success_object(serialize(sub))


@bp.post("/subscriptions/<id>/withdraw")
def withdraw_subscription(id):
    require_role("UtilityParticipant")
    sub = get_or_404("subscription", id)
    _own_sub(sub)
    if sub["status"] != "EXECUTED":
        raise _invalid("commitment is not EXECUTED")
    body = json_body()
    expected = v_int(body, "expected_cost_share_agreement_version")
    csa = next((c for c in DB["cost_share_agreement"].values()
                if c["dca_id"] == sub["dca_id"]), None)
    if csa is None:
        raise ApiError(ERR_STALE_VERSION, 412, "no cost-share agreement observed")
    if csa["version"] != expected:
        raise ApiError(ERR_STALE_VERSION, 412,
                       "cost-share agreement version has advanced")

    executed_dt = parse_iso(sub["executed_at"]) if sub.get("executed_at") else None
    penalty = withdrawal_penalty(sub.get("withdrawal_reserve_usd", 0), executed_dt, get_clock())
    sub["offload_penalty_usd"] = penalty
    sub["status"] = "WITHDRAWN"
    touch(sub)
    dca = get_or_404("dca", sub["dca_id"])
    recompute_dca_subscription_fields(sub["dca_id"])
    touch(dca)
    recompute_csa_allocated(sub["dca_id"])
    touch(csa)
    return success_object(serialize(sub))


# ---------------------------------------------------------------------------
# Cost-share agreements
# ---------------------------------------------------------------------------
@bp.post("/cost-share-agreements")
def create_csa():
    require_role("DoeProgram")
    body = json_body()
    dca_id = v_str(body, "dca_id")
    get_or_404("dca", dca_id)
    total = v_int(body, "total_cost_usd", minimum=0, exclusive_min=True)
    gov = v_int(body, "gov_contribution_usd", minimum=0)
    if gov >= total:
        raise ApiError("ERR_VALIDATION", 400,
                       "gov_contribution_usd must be strictly less than total_cost_usd")
    if any(c["dca_id"] == dca_id for c in DB["cost_share_agreement"].values()):
        raise ApiError(ERR_DUPLICATE, 409, "agreement already exists for this application")
    csa = base_record("cost_share_agreement", {
        "dca_id": dca_id,
        "total_cost_usd": total,
        "gov_contribution_usd": gov,
        "participant_share_usd": total - gov,
        "allocated_to_participants_usd": 0,
    })
    DB["cost_share_agreement"][csa["id"]] = csa
    return success_object(serialize(csa), status=201)


@bp.get("/cost-share-agreements")
def list_csas():
    require_role()
    items = list(DB["cost_share_agreement"].values())
    dca_id = request.args.get("dca_id")
    if dca_id is not None:
        items = [c for c in items if c["dca_id"] == dca_id]
    items = sort_by_created(items)
    limit, offset = paginate_args(request.args)
    page, total = apply_pagination(items, limit, offset)
    return success_list([serialize(c) for c in page], total, limit, offset)


@bp.get("/cost-share-agreements/<id>")
def get_csa(id):
    require_role()
    return success_object(serialize(get_or_404("cost_share_agreement", id)))


@bp.post("/cost-share-agreements/<id>/escalate")
def escalate_csa(id):
    require_role("DoeProgram")
    csa = get_or_404("cost_share_agreement", id)
    body = json_body()
    overrun = v_int(body, "overrun_usd")
    if overrun <= 0 or overrun > 3 * csa["participant_share_usd"]:
        raise ApiError(ERR_ESCALATION_OUT_OF_RANGE, 422,
                       "overrun_usd must be > 0 and at most 3x participant_share_usd")
    dca = get_or_404("dca", csa["dca_id"])
    escalate_reallocate(csa, dca, overrun)
    recompute_csa_allocated(csa["dca_id"])
    recompute_dca_subscription_fields(csa["dca_id"])
    touch(csa)
    return success_object(serialize(csa))
