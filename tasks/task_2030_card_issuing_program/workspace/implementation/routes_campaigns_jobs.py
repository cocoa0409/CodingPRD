"""ReissueCampaign and ConversionJob endpoints."""
from flask import Blueprint, request

from core import (
    STORE, ApiError, ok, ok_list, body, req_field, req_enum, opt_int,
    new_entity, touch, pub, sort_created, get_or_404, require_roles,
    parse_dt, fmt_dt, now, select_campaign_cards, current_user_id,
    CAMPAIGN_KINDS,
)

bp = Blueprint("campaigns_jobs", __name__)

CAMPAIGN_READ = ("ProgramManager", "OperationsAnalyst", "FinanceController",
                 "PlatformAdmin")


def _get_program(pid):
    return get_or_404("programs", pid, "program")


def _get_campaign(cid):
    return get_or_404("campaigns", cid, "reissue campaign")


def _get_job(jid):
    return get_or_404("jobs", jid, "conversion job")


# ---------------------------------------------------------------------------
# ReissueCampaign
# ---------------------------------------------------------------------------

@bp.post("/issuing/programs/<pid>/reissue-campaigns")
@require_roles("OperationsAnalyst")
def create_campaign(pid):
    _get_program(pid)
    data = body()
    kind = req_enum(data, "campaign_kind", CAMPAIGN_KINDS)
    try:
        scheduled_for = parse_dt(req_field(data, "scheduled_for"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "scheduled_for must be an ISO8601 timestamp")
    if not scheduled_for > now():
        raise ApiError("ERR_CAMPAIGN_DATE_PAST", 409,
                       "scheduled_for must be strictly in the future")
    selection_filter = data.get("selection_filter") or {}
    if not isinstance(selection_filter, dict):
        raise ApiError("ERR_VALIDATION", 400, "selection_filter must be an object")
    targeted = opt_int(data, "targeted_unit_fee_cents", default=None, min_value=0)
    blanket = opt_int(data, "blanket_unit_fee_cents", default=None, min_value=0)
    c = new_entity()
    c.update({
        "program_id": pid,
        "campaign_kind": kind,
        "scheduled_for": fmt_dt(scheduled_for),
        "selection_filter": selection_filter,
        "targeted_unit_fee_cents": targeted,
        "blanket_unit_fee_cents": blanket,
        "estimated_card_count": 0,
        "status": "DRAFT",
        "empty_execution_reason": None,
        "booked_fee_cents": None,
        "_scheduled_for": scheduled_for,
        "_booked_fee_cents": 0,
        "_completed_at": None,
    })
    STORE["campaigns"][c["id"]] = c
    return ok(pub(c), 201)


@bp.get("/issuing/programs/<pid>/reissue-campaigns")
@require_roles(*CAMPAIGN_READ)
def list_campaigns(pid):
    _get_program(pid)
    items = [c for c in STORE["campaigns"].values() if c["program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    kind = request.args.get("campaign_kind")
    if kind is not None:
        items = [c for c in items if c["campaign_kind"] == kind]
    return ok_list([pub(c) for c in sort_created(items)])


@bp.get("/issuing/reissue-campaigns/<cid>")
@require_roles(*CAMPAIGN_READ)
def get_campaign(cid):
    return ok(pub(_get_campaign(cid)))


@bp.get("/issuing/reissue-campaigns/<cid>/cards")
@require_roles("ProgramManager", "OperationsAnalyst", "PlatformAdmin")
def list_campaign_cards(cid):
    _get_campaign(cid)
    items = [c for c in STORE["cards"].values()
             if c.get("reissue_campaign_id") == cid]
    return ok_list([pub(c) for c in sort_created(items)])


@bp.post("/issuing/reissue-campaigns/<cid>/schedule")
@require_roles("OperationsAnalyst")
def schedule_campaign(cid):
    c = _get_campaign(cid)
    if c["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "schedule requires status DRAFT")
    if not c["_scheduled_for"] > now():
        raise ApiError("ERR_CAMPAIGN_DATE_PAST", 409,
                       "scheduled_for is not strictly in the future")
    selected = select_campaign_cards(c)
    if len(selected) < 1:
        raise ApiError("ERR_CAMPAIGN_EMPTY_SELECTION", 409,
                       "selection filter matches no cards")
    c["estimated_card_count"] = len(selected)
    c["status"] = "SCHEDULED"
    touch(c)
    return ok(pub(c))


@bp.post("/issuing/reissue-campaigns/<cid>/cancel")
@require_roles("OperationsAnalyst")
def cancel_campaign(cid):
    c = _get_campaign(cid)
    if c["status"] not in ("DRAFT", "SCHEDULED"):
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel requires status DRAFT or SCHEDULED")
    c["status"] = "CANCELLED"
    touch(c)
    return ok(pub(c))


# ---------------------------------------------------------------------------
# ConversionJob
# ---------------------------------------------------------------------------

@bp.post("/issuing/programs/<pid>/conversion-jobs")
@require_roles("ProgramManager")
def create_job(pid):
    src = _get_program(pid)
    if src["posture"] != "SUNSETTING":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "conversion jobs require the source program to be SUNSETTING")
    data = body()
    try:
        execution_at = parse_dt(req_field(data, "execution_at"))
    except (ValueError, TypeError):
        raise ApiError("ERR_VALIDATION", 400,
                       "execution_at must be an ISO8601 timestamp")
    if not execution_at > now():
        raise ApiError("ERR_CONVERSION_DATE_PAST", 409,
                       "execution_at must be strictly in the future")
    target_program_id = req_field(data, "target_program_id")
    tgt = STORE["programs"].get(target_program_id) \
        if isinstance(target_program_id, str) else None
    if tgt is None:
        raise ApiError("ERR_INVALID_REFERENCE", 422,
                       "target_program_id does not resolve to an existing program")
    if tgt["id"] == src["id"] or tgt["posture"] != "LIVE" or \
            tgt["network"] != src["network"] or \
            tgt["currency_code"] != src["currency_code"]:
        raise ApiError("ERR_CONVERSION_TARGET_INVALID", 409,
                       "target must be a different LIVE program on the same "
                       "network and currency")
    planned = sum(1 for a in STORE["accounts"].values()
                  if a["program_id"] == pid and
                  a["lifecycle_status"] in ("OPEN", "SUSPENDED"))
    j = new_entity()
    j.update({
        "source_program_id": pid,
        "target_program_id": target_program_id,
        "execution_at": fmt_dt(execution_at),
        "accounts_planned": planned,
        "accounts_converted": 0,
        "status": "SCHEDULED",
        "_execution_at": execution_at,
        "_created_by_user_id": current_user_id(),
    })
    STORE["jobs"][j["id"]] = j
    return ok(pub(j), 201)


@bp.get("/issuing/programs/<pid>/conversion-jobs")
@require_roles("ProgramManager", "PlatformAdmin")
def list_jobs(pid):
    _get_program(pid)
    items = [j for j in STORE["jobs"].values() if j["source_program_id"] == pid]
    status = request.args.get("status")
    if status is not None:
        items = [j for j in items if j["status"] == status]
    return ok_list([pub(j) for j in sort_created(items)])


@bp.get("/issuing/conversion-jobs/<jid>")
@require_roles("ProgramManager", "PlatformAdmin")
def get_job(jid):
    return ok(pub(_get_job(jid)))


@bp.post("/issuing/conversion-jobs/<jid>/cancel")
@require_roles("ProgramManager")
def cancel_job(jid):
    j = _get_job(jid)
    if j["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "cancel requires status SCHEDULED")
    if current_user_id() == j.get("_created_by_user_id"):
        raise ApiError("ERR_SOD_SAME_USER", 409,
                       "the scheduling operator may not cancel the job")
    j["status"] = "CANCELLED"
    touch(j)
    return ok(pub(j))
