"""Signing the book (§3.3), re-signing / removal and the housekeeping
sweep (§3.4)."""

from flask import Blueprint

from core import (
    LAYOFF_REREG_WINDOW_DAYS, MANUAL_REMOVAL_REASONS, REGISTRATION_STATUSES,
    RESIGN_INTERVAL_DAYS, RETENTION_DAYS, BASIS_POINT_SCALE,
    db, days, iso, new_id, now, round_half_up_div, touch,
)
from envelope import ApiError, created, listing, ok
from guards import (
    authenticate, body, check_pagination_shape, pagination, paginate, q_enum,
    q_str, require, s_bool, s_enum, s_reciprocity_credits, s_str,
)
import domain
import serializers as S
import services

bp = Blueprint("reg", __name__)


def _credited_seniority_hours(member, credits):
    """§3.3 / §2.9 — each declared credit is rounded to whole hours on its own,
    and only the rounded per-entry results are summed."""
    total = member["local_hours_in_trade"]
    for credit in credits:
        local = db.locals.get(credit["sister_local_id"])
        factor = local["reciprocity_factor_bp"] if local else 0
        total += round_half_up_div(credit["raw_hours"] * factor, BASIS_POINT_SCALE)
    return total


def _qualifying_layoff_dispatch(predecessor):
    """The predecessor's own referrals, and the dispatch one of them produced,
    when that dispatch ended in LAID_OFF."""
    referral_ids = [r["id"] for r in db.referrals.values()
                    if r["registration_id"] == predecessor["id"]]
    matches = [d for d in db.dispatches.values()
               if d["referral_id"] in referral_ids and d["status"] == "LAID_OFF"]
    matches.sort(key=lambda d: (d["created_at"], d["_seq"]))
    return matches[-1] if matches else None


@bp.route("/hiring-hall/registrations", methods=["POST"])
def create_registration():
    user_id, role = require("HallAdmin", "Dispatcher", "Member")
    check_pagination_shape()
    data = body()
    member_id = s_str(data, "member_id")
    list_id = s_str(data, "list_id")
    predecessor_id = s_str(data, "predecessor_registration_id", required=False,
                           default=None)
    claim = s_bool(data, "claim_position_preservation", required=False, default=False)
    credits = s_reciprocity_credits(data)

    # 5 — body foreign keys, in the order §2.6 states them
    member = db.members.get(member_id)
    if member is None:
        raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)
    group = db.lists.get(list_id)
    if group is None:
        raise ApiError("ERR_LIST_NOT_FOUND", "No out-of-work list with id %s." % list_id)
    predecessor = None
    if predecessor_id is not None:
        predecessor = db.registrations.get(predecessor_id)
        if predecessor is None:
            raise ApiError("ERR_REGISTRATION_NOT_FOUND",
                           "No registration with id %s." % predecessor_id)
    for credit in credits:
        if credit["sister_local_id"] not in db.locals:
            raise ApiError("ERR_LOCAL_NOT_FOUND",
                           "No local with id %s." % credit["sister_local_id"])

    # 6 — ownership
    if role == "Member" and user_id != member_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A member may only sign the out-of-work list for itself.")

    # 20 — list-group eligibility
    if member["local_hours_in_trade"] < group["requires_local_hours"]:
        raise ApiError("ERR_LIST_GROUP_NOT_ELIGIBLE",
                       "Member local hours are below the group's floor.")
    if domain.member_is_traveler(member) and not group["accepts_travelers"]:
        raise ApiError("ERR_LIST_GROUP_NOT_ELIGIBLE",
                       "This list group does not accept travelers.")

    # 21 — reciprocity eligibility
    if domain.member_is_traveler(member):
        home = db.locals.get(member["home_local_id"])
        if home is None or home["reciprocity_factor_bp"] <= 0:
            raise ApiError("ERR_TRAVELER_NOT_RECIPROCAL",
                           "The traveler's home local carries no reciprocity agreement.")
    for credit in credits:
        local = db.locals[credit["sister_local_id"]]
        if local["kind"] != "SISTER" or local["reciprocity_factor_bp"] <= 0:
            raise ApiError("ERR_TRAVELER_NOT_RECIPROCAL",
                           "Local %s carries no reciprocity agreement." % local["id"])

    # 22 — predecessor belongs to the same member
    if predecessor is not None and predecessor["member_id"] != member_id:
        raise ApiError("ERR_REREGISTRATION_PREDECESSOR_MISMATCH",
                       "The predecessor registration belongs to another member.")

    # 25 — cooling-off period
    eligible_at = member["re_registration_eligible_at"]
    if eligible_at is not None and now() < eligible_at:
        raise ApiError("ERR_REREGISTRATION_TOO_EARLY",
                       "The re-registration cooling-off period has not elapsed.")

    # 26 — the post-layoff position-preservation window
    preserved = False
    if claim:
        dispatch = _qualifying_layoff_dispatch(predecessor) if predecessor else None
        if dispatch is None or dispatch["ended_at"] is None:
            raise ApiError("ERR_REREGISTRATION_WINDOW_EXPIRED",
                           "No layoff dispatch supports a position-preservation claim.")
        horizon = dispatch["ended_at"] + days(LAYOFF_REREG_WINDOW_DAYS)
        if now() > horizon:
            raise ApiError("ERR_REREGISTRATION_WINDOW_EXPIRED",
                           "The five-day post-layoff window has closed.")
        preserved = True

    # 32 — at most one live registration across every list
    for existing in db.registrations.values():
        if existing["member_id"] == member_id and existing["status"] in ("REGISTERED", "REFERRED"):
            raise ApiError("ERR_MEMBER_ALREADY_REGISTERED",
                           "The member already holds a live registration.")

    clock = now()
    registered_at = predecessor["registered_at"] if preserved else clock
    demotion_count = predecessor["demotion_count"] if preserved else 0
    record = {
        "id": new_id(),
        "member_id": member_id,
        "list_id": list_id,
        "predecessor_registration_id": predecessor_id,
        "claim_position_preservation": claim,
        "reciprocity_credits": credits,
        "registered_at": registered_at,
        "last_renewed_at": clock,
        "renewal_due_at": clock + days(RESIGN_INTERVAL_DAYS),
        "credited_seniority_hours": _credited_seniority_hours(member, credits),
        "demotion_count": demotion_count,
        "priority_flag": False,
        "status": "REGISTERED",
        "removal_reason": None,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.registrations[record["id"]] = record
    services.append_ledger("REGISTRATION_CREATED", member_id,
                           snapshot={"registration_id": record["id"],
                                     "list_id": list_id,
                                     "credited_seniority_hours":
                                         record["credited_seniority_hours"]},
                           retention_from=registered_at)
    if preserved:
        services.append_ledger("POSITION_RESTORED", member_id,
                               snapshot={"registration_id": record["id"],
                                         "predecessor_registration_id": predecessor_id})
    return created(S.registration_view(record))


@bp.route("/hiring-hall/registrations/<registration_id>", methods=["GET"])
def read_registration(registration_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    check_pagination_shape()
    record = db.registrations.get(registration_id)
    if record is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND",
                       "No registration with id %s." % registration_id)
    return ok(S.registration_view(record))


@bp.route("/hiring-hall/registrations", methods=["GET"])
def list_registrations():
    require("HallAdmin", "Dispatcher", "BusinessManager", "Member")
    member_id = q_str("member_id")
    list_id = q_str("list_id")
    status = q_enum("status", REGISTRATION_STATUSES)
    predecessor_id = q_str("predecessor_registration_id")
    limit, offset = pagination()
    rows = services.sort_default(db.registrations.values())
    if member_id is not None:
        rows = [r for r in rows if r["member_id"] == member_id]
    if list_id is not None:
        rows = [r for r in rows if r["list_id"] == list_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if predecessor_id is not None:
        rows = [r for r in rows if r["predecessor_registration_id"] == predecessor_id]
    page, meta = paginate(rows, limit, offset)
    return listing([S.registration_view(r) for r in page], meta)


@bp.route("/hiring-hall/registrations/<registration_id>/renew", methods=["POST"])
def renew_registration(registration_id):
    user_id, role = require("HallAdmin", "Dispatcher", "Member")
    check_pagination_shape()
    body()
    record = db.registrations.get(registration_id)
    if record is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND",
                       "No registration with id %s." % registration_id)
    if role == "Member" and user_id != record["member_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A member may only re-sign their own registration.")
    if record["status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_ACTIVE",
                       "Only a REGISTERED registration may be re-signed.")
    clock = now()
    record["last_renewed_at"] = clock
    record["renewal_due_at"] = clock + days(RESIGN_INTERVAL_DAYS)
    touch(record)
    services.append_ledger("REGISTRATION_RENEWED", record["member_id"],
                           snapshot={"registration_id": record["id"]})
    return ok(S.registration_view(record))


@bp.route("/hiring-hall/registrations/<registration_id>/remove", methods=["POST"])
def remove_registration_route(registration_id):
    require("HallAdmin", "Dispatcher")
    check_pagination_shape()
    data = body()
    reason = s_enum(data, "reason", MANUAL_REMOVAL_REASONS)
    record = db.registrations.get(registration_id)
    if record is None:
        raise ApiError("ERR_REGISTRATION_NOT_FOUND",
                       "No registration with id %s." % registration_id)
    if record["status"] != "REGISTERED":
        raise ApiError("ERR_REGISTRATION_NOT_ACTIVE",
                       "Only a REGISTERED registration may be removed.")
    services.remove_registration(record, reason)
    services.append_ledger("REGISTRATION_REMOVED", record["member_id"],
                           snapshot={"registration_id": record["id"],
                                     "removal_reason": reason})
    return ok(S.registration_view(record))


# --------------------------------------------------------------------------
# §3.4 the housekeeping sweep — four steps, in this fixed order
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/dispatch-runs", methods=["POST"])
def dispatch_run():
    require("HallAdmin", "Dispatcher")
    check_pagination_shape()
    body()
    clock = now()

    expired_referral_count = 0
    demoted_registration_count = 0
    removed_registration_count = 0
    expired_registration_count = 0
    purged_ledger_entry_count = 0

    # step one — expire stale referrals
    stale = [r for r in db.referrals.values()
             if r["status"] == "ISSUED" and r["acceptance_deadline"] < clock]
    stale.sort(key=lambda r: (r["acceptance_deadline"], r["created_at"], r["_seq"]))
    for referral in stale:
        referral["status"] = "EXPIRED"
        touch(referral)
        expired_referral_count += 1

    # step two — apply the strike consequences of those expiries
    for referral in stale:
        registration = db.registrations.get(referral["registration_id"])
        outcome = services.apply_no_cause_consequence(referral, registration,
                                                      expired_event=True)
        if outcome == "REMOVED":
            removed_registration_count += 1
        else:
            demoted_registration_count += 1
        job_request = db.job_requests.get(referral["job_request_id"])
        if job_request is not None:
            services.rederive_job_request_status(job_request)
            touch(job_request)

    # step three — expire lapsed registrations
    lapsed = [r for r in db.registrations.values()
              if r["status"] == "REGISTERED" and r["renewal_due_at"] < clock]
    lapsed.sort(key=lambda r: (r["renewal_due_at"], r["created_at"], r["_seq"]))
    for registration in lapsed:
        registration["status"] = "EXPIRED"
        registration["removal_reason"] = "RENEWAL_LAPSED"
        touch(registration)
        expired_registration_count += 1
        services.append_ledger("REGISTRATION_EXPIRED", registration["member_id"],
                               snapshot={"registration_id": registration["id"],
                                         "removal_reason": "RENEWAL_LAPSED"})

    # step four — purge the aged dispatch record
    for entry in services.sort_default(db.ledger.values()):
        if entry["purge_state"] == "RETAINED" and entry["retention_until"] < clock:
            entry["purge_state"] = "PURGED"
            entry["snapshot_json"] = None
            purged_ledger_entry_count += 1

    return ok({
        "run_at": iso(clock),
        "expired_referral_count": expired_referral_count,
        "demoted_registration_count": demoted_registration_count,
        "removed_registration_count": removed_registration_count,
        "expired_registration_count": expired_registration_count,
        "purged_ledger_entry_count": purged_ledger_entry_count,
    })
