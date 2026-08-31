"""Insurance authorization: submission, decisions, awards and appeals
(PRD 3.6)."""

from flask import Blueprint

import calc
import cascade
import derive
from envelope import created, filter_eq, list_response, ok
from errors import ApiError
from store import add_days, base_row, db, fmt_dt, ordered, touch
from validate import (DECISIONS, DENIAL_REASONS, LEVELS_OF_CARE, actor, body,
                      present, req_enum, req_int, req_str, require_roles)

bp = Blueprint("authorizations", __name__)


@bp.post("/episodes/<eid>/authorizations")
def create_authorization(eid):
    require_roles("CaseManager")
    episode = derive.get_episode(eid)
    derive.sweep_episode(episode)
    b = body()
    provider_id = req_str(b, "provider_id")
    level = req_enum(b, "level_of_care", LEVELS_OF_CARE)
    requested_days = req_int(b, "requested_days", minimum=1)
    billed_rate = req_int(b, "billed_daily_rate_cents", minimum=1)
    provider = derive.get_provider(provider_id)
    if provider["provider_type"] != level:
        raise ApiError("ERR_PROVIDER_TYPE_MISMATCH",
                       "level_of_care does not match the provider's provider_type")
    patient = derive.get_patient(episode["patient_id"])
    row = base_row()
    row.update({
        "episode_id": episode["id"],
        "payer_id": patient["primary_payer_id"],
        "provider_id": provider_id,
        "level_of_care": level,
        "requested_days": requested_days,
        "billed_daily_rate_cents": billed_rate,
        "approved_days": None,
        "appeal_round": 0,
        "status": "SUBMITTED",
        "denial_reason": None,
        "decided_at": None,
        "expires_at": None,
        "rate_variant_applied": None,
        "gross_projection_cents": 0,
        "volume_discount_pct": 0.0,
        "authorized_amount_cents": 0,
    })
    db.authorizations[row["id"]] = row
    if cascade.advance_to_planning(episode):
        touch(episode)
    return created(derive.ser_authorization(row))


def _award(auth, approved_days):
    contract = derive.contract_for(auth["payer_id"], auth["provider_id"])
    award = calc.authorization_award(contract, auth["billed_daily_rate_cents"], approved_days)
    auth.update(award)


@bp.post("/authorizations/<aid>/decide")
def decide(aid):
    require_roles("PayerRepresentative")
    if db.payers.get(actor()) is None:
        raise ApiError("ERR_NOT_OWNER", "X-User-ID does not identify a payer")
    auth = derive.get_authorization(aid)
    if auth["payer_id"] != actor():
        raise ApiError("ERR_NOT_OWNER", "this authorization belongs to another payer")
    derive.sweep_authorization(auth)
    episode = derive.get_episode(auth["episode_id"])

    b = body()
    decision = req_enum(b, "decision", DECISIONS)
    approved_days = None
    if decision == "PARTIAL":
        approved_days = req_int(b, "approved_days", minimum=1)
        if approved_days >= auth["requested_days"]:
            raise ApiError("ERR_VALIDATION",
                           "approved_days must be strictly fewer than requested_days")
    elif present(b, "approved_days"):
        raise ApiError("ERR_VALIDATION", "approved_days is only allowed for a PARTIAL decision")
    denial_reason = None
    if decision == "DENY":
        denial_reason = req_enum(b, "denial_reason", DENIAL_REASONS)
    elif present(b, "denial_reason"):
        raise ApiError("ERR_VALIDATION", "denial_reason is only allowed for a DENY decision")

    if auth["status"] not in ("SUBMITTED", "PENDED"):
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE",
                       "authorization status %s does not admit a decision" % auth["status"])
    if decision == "PEND" and auth["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE",
                       "PEND is only available as a first response")

    now_iso = db.now_iso()
    if decision == "PEND":
        auth["status"] = "PENDED"
        auth["decided_at"] = now_iso
    elif decision in ("APPROVE", "PARTIAL"):
        granted = auth["requested_days"] if decision == "APPROVE" else approved_days
        payer = derive.get_payer(auth["payer_id"])
        auth["approved_days"] = granted
        auth["decided_at"] = now_iso
        auth["expires_at"] = fmt_dt(add_days(db.now(), payer["auth_expiry_days"]))
        auth["status"] = "APPROVED" if decision == "APPROVE" else "PARTIALLY_APPROVED"
        _award(auth, granted)
        cascade.resolve_barriers_with_code(episode, "INSURANCE_AUTH")
    else:
        auth["approved_days"] = 0
        auth["denial_reason"] = denial_reason
        auth["decided_at"] = now_iso
        auth["expires_at"] = None
        auth["status"] = "DENIED"
        cascade.denial_cascade(episode)
    touch(auth)
    return ok(derive.ser_authorization(auth))


@bp.post("/authorizations/<aid>/appeal")
def appeal(aid):
    require_roles("UtilizationReviewNurse", "CaseManager")
    auth = derive.get_authorization(aid)
    derive.sweep_authorization(auth)
    b = body()
    req_str(b, "appeal_note")
    if auth["status"] != "DENIED":
        raise ApiError("ERR_INVALID_AUTHORIZATION_STATE",
                       "only a DENIED authorization may be appealed")
    if auth["appeal_round"] >= calc.MAX_APPEAL_ROUNDS:
        raise ApiError("ERR_APPEAL_LIMIT_REACHED", "the appeal limit has been reached")
    auth["appeal_round"] += 1
    auth["status"] = "SUBMITTED"
    auth["denial_reason"] = None
    auth["decided_at"] = None
    auth["approved_days"] = None
    auth["gross_projection_cents"] = 0
    auth["volume_discount_pct"] = 0.0
    auth["authorized_amount_cents"] = 0
    touch(auth)
    return ok(derive.ser_authorization(auth))


@bp.get("/authorizations/<aid>")
def read_authorization(aid):
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "PayerRepresentative")
    auth = derive.get_authorization(aid)
    derive.sweep_authorization(auth)
    return ok(derive.ser_authorization(auth))


@bp.get("/authorizations")
def list_authorizations():
    require_roles("CaseManager", "UtilizationReviewNurse", "PlatformAdmin",
                  "PayerRepresentative")
    rows = ordered(db.authorizations.values())
    for row in rows:
        derive.sweep_authorization(row)
    rows = filter_eq(rows, "episode_id", "episode_id")
    rows = filter_eq(rows, "payer_id", "payer_id")
    rows = filter_eq(rows, "provider_id", "provider_id")
    rows = filter_eq(rows, "status", "status")
    return list_response(rows, derive.ser_authorization)
