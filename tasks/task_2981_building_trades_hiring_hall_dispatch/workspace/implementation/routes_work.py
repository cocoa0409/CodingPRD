"""The contractor side: contractor records, delinquency cascade, job-request
intake, cancellation, the dispatch-order read and referral issuance
(§3.5, §3.6)."""

from flask import Blueprint

from core import (
    ACCEPTANCE_WINDOW_HOURS, DURATION_TYPES, JOB_REQUEST_STATUSES,
    REFERRAL_KINDS, SIGNATORY_STATUSES, SKILL_CODES, SLOT_KINDS,
    db, hours, new_id, now, touch,
)
from envelope import ApiError, created, listing, ok
from guards import (
    body, check_pagination_shape, pagination, paginate, q_enum, q_str, require,
    s_enum, s_id_array, s_int, s_str,
)
import domain
import serializers as S
import services

bp = Blueprint("work", __name__)


# --------------------------------------------------------------------------
# contractors
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/contractors", methods=["POST"])
def create_contractor():
    require("HallAdmin")
    check_pagination_shape()
    data = body()
    from guards import s_dt
    name = s_str(data, "name", min_len=1, max_len=120)
    agreement_expires_at = s_dt(data, "agreement_expires_at")
    signatory_status = s_enum(data, "signatory_status", SIGNATORY_STATUSES,
                              required=False, default="SIGNATORY")
    clock = now()
    record = {
        "id": new_id(),
        "name": name,
        "agreement_expires_at": agreement_expires_at,
        "signatory_status": signatory_status,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.contractors[record["id"]] = record
    return created(S.contractor_view(record))


@bp.route("/hiring-hall/contractors/<contractor_id>", methods=["GET"])
def read_contractor(contractor_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep")
    check_pagination_shape()
    record = db.contractors.get(contractor_id)
    if record is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND",
                       "No contractor with id %s." % contractor_id)
    return ok(S.contractor_view(record))


@bp.route("/hiring-hall/contractors", methods=["GET"])
def list_contractors():
    require("HallAdmin", "Dispatcher", "BusinessManager")
    signatory_status = q_enum("signatory_status", SIGNATORY_STATUSES)
    limit, offset = pagination()
    rows = services.sort_default(db.contractors.values())
    if signatory_status is not None:
        rows = [r for r in rows if r["signatory_status"] == signatory_status]
    page, meta = paginate(rows, limit, offset)
    return listing([S.contractor_view(r) for r in page], meta)


@bp.route("/hiring-hall/contractors/<contractor_id>/signatory-status", methods=["PATCH"])
def patch_signatory_status(contractor_id):
    require("HallAdmin", "BusinessManager")
    check_pagination_shape()
    data = body()
    signatory_status = s_enum(data, "signatory_status", SIGNATORY_STATUSES)
    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND",
                       "No contractor with id %s." % contractor_id)
    previous = contractor["signatory_status"]
    contractor["signatory_status"] = signatory_status
    touch(contractor)

    requests = [j for j in services.sort_default(db.job_requests.values())
                if j["contractor_id"] == contractor_id]
    if signatory_status in ("DELINQUENT_TRUST_FUNDS", "TERMINATED"):
        # hop one — suspend the live work, remembering where it came from
        suspended = []
        for job_request in requests:
            if job_request["status"] in ("OPEN", "PARTIALLY_FILLED"):
                job_request["suspended_from_status"] = job_request["status"]
                job_request["status"] = "SUSPENDED"
                touch(job_request)
                suspended.append(job_request)
        # hops two, three and four — withdraw, restore, record
        for job_request in suspended:
            services.withdraw_issued_referrals_of_job_request(
                job_request, reason="CONTRACTOR_DELINQUENT",
                bump_job_request_version=False)
    elif signatory_status == "SIGNATORY" and previous != "SIGNATORY":
        # reinstatement is not symmetric: nothing is reissued
        for job_request in requests:
            if job_request["status"] == "SUSPENDED":
                job_request["status"] = job_request["suspended_from_status"] or "OPEN"
                job_request["suspended_from_status"] = None
                touch(job_request)
    return ok(S.contractor_view(contractor))


# --------------------------------------------------------------------------
# job requests
# --------------------------------------------------------------------------
@bp.route("/hiring-hall/job-requests", methods=["POST"])
def create_job_request():
    user_id, role = require("ContractorRep", "Dispatcher")
    check_pagination_shape()
    data = body()
    from guards import s_dt
    contractor_id = s_str(data, "contractor_id")
    job_site = s_str(data, "job_site", min_len=1, max_len=160)
    journeyworkers = s_int(data, "journeyworkers_requested", minimum=0, maximum=40)
    apprentices = s_int(data, "apprentices_requested", minimum=0, maximum=40)
    expected_duration_days = s_int(data, "expected_duration_days", minimum=1,
                                   maximum=3650)
    report_at = s_dt(data, "report_at")
    hourly_rate_cents = s_int(data, "hourly_rate_cents", minimum=1, maximum=99999)
    required_skill_code = s_enum(data, "required_skill_code", SKILL_CODES,
                                 required=False, default=None)
    special_skill_slots = s_int(data, "special_skill_slots_requested",
                                required=False, minimum=0, maximum=40, default=0)
    named_call_member_ids = s_id_array(data, "named_call_member_ids", default=[])
    if journeyworkers + apprentices < 1:
        raise ApiError("ERR_INVALID_REQUEST",
                       "At least one worker must be requested across the two headcounts.")

    contractor = db.contractors.get(contractor_id)
    if contractor is None:
        raise ApiError("ERR_CONTRACTOR_NOT_FOUND",
                       "No contractor with id %s." % contractor_id)
    for member_id in named_call_member_ids:
        if member_id not in db.members:
            raise ApiError("ERR_MEMBER_NOT_FOUND", "No member with id %s." % member_id)

    if role == "ContractorRep" and user_id != contractor_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A representative may only open work for its own contractor.")

    if contractor["signatory_status"] != "SIGNATORY":
        raise ApiError("ERR_CONTRACTOR_NOT_SIGNATORY",
                       "The contractor is not currently signatory.")

    duration_type = domain.duration_type_for(expected_duration_days)
    named_allowance, special_allowance = domain.compute_allowances(
        journeyworkers, apprentices, duration_type, required_skill_code)
    if len(named_call_member_ids) > named_allowance:
        raise ApiError("ERR_NAMED_CALL_ALLOWANCE_EXCEEDED",
                       "The request permits at most %d named calls." % named_allowance)
    if special_skill_slots > special_allowance:
        raise ApiError("ERR_SPECIAL_SKILL_ALLOWANCE_EXCEEDED",
                       "The request permits at most %d special-skill slots."
                       % special_allowance)

    clock = now()
    record = {
        "id": new_id(),
        "contractor_id": contractor_id,
        "job_site": job_site,
        "journeyworkers_requested": journeyworkers,
        "apprentices_requested": apprentices,
        "expected_duration_days": expected_duration_days,
        "report_at": report_at,
        "hourly_rate_cents": hourly_rate_cents,
        "required_skill_code": required_skill_code,
        "special_skill_slots_requested": special_skill_slots,
        "named_call_member_ids": named_call_member_ids,
        "duration_type": duration_type,
        "named_call_allowance": named_allowance,
        "special_skill_allowance": special_allowance,
        "status": "OPEN",
        "suspended_from_status": None,
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.job_requests[record["id"]] = record
    return created(S.job_request_view(record))


@bp.route("/hiring-hall/job-requests/<job_request_id>", methods=["GET"])
def read_job_request(job_request_id):
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep")
    check_pagination_shape()
    record = db.job_requests.get(job_request_id)
    if record is None:
        raise ApiError("ERR_JOB_REQUEST_NOT_FOUND",
                       "No job request with id %s." % job_request_id)
    return ok(S.job_request_view(record))


@bp.route("/hiring-hall/job-requests", methods=["GET"])
def list_job_requests():
    require("HallAdmin", "Dispatcher", "BusinessManager", "ContractorRep")
    contractor_id = q_str("contractor_id")
    status = q_enum("status", JOB_REQUEST_STATUSES)
    duration_type = q_enum("duration_type", DURATION_TYPES)
    limit, offset = pagination()
    rows = services.sort_default(db.job_requests.values())
    if contractor_id is not None:
        rows = [r for r in rows if r["contractor_id"] == contractor_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if duration_type is not None:
        rows = [r for r in rows if r["duration_type"] == duration_type]
    page, meta = paginate(rows, limit, offset)
    return listing([S.job_request_view(r) for r in page], meta)


@bp.route("/hiring-hall/job-requests/<job_request_id>/cancel", methods=["POST"])
def cancel_job_request(job_request_id):
    user_id, role = require("ContractorRep", "HallAdmin")
    check_pagination_shape()
    data = body()
    reason = s_str(data, "reason", min_len=1, max_len=500)
    job_request = db.job_requests.get(job_request_id)
    if job_request is None:
        raise ApiError("ERR_JOB_REQUEST_NOT_FOUND",
                       "No job request with id %s." % job_request_id)
    if role == "ContractorRep" and user_id != job_request["contractor_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER",
                       "A representative may only cancel its own job requests.")
    if job_request["status"] not in ("OPEN", "PARTIALLY_FILLED", "SUSPENDED"):
        raise ApiError("ERR_JOB_REQUEST_NOT_OPEN",
                       "A %s job request cannot be cancelled." % job_request["status"])
    job_request["status"] = "CANCELLED"
    job_request["suspended_from_status"] = None
    touch(job_request)
    services.withdraw_issued_referrals_of_job_request(
        job_request, reason=reason, bump_job_request_version=False)
    return ok(S.job_request_view(job_request))


@bp.route("/hiring-hall/job-requests/<job_request_id>/dispatch-order", methods=["GET"])
def read_dispatch_order(job_request_id):
    require("HallAdmin", "Dispatcher", "BusinessManager")
    slot_kind = q_enum("slot_kind", SLOT_KINDS)
    if slot_kind is None:
        raise ApiError("ERR_INVALID_REQUEST", "Query parameter 'slot_kind' is required.")
    referral_kind = q_enum("referral_kind", REFERRAL_KINDS) or "LIST_ORDER"
    check_pagination_shape()
    job_request = db.job_requests.get(job_request_id)
    if job_request is None:
        raise ApiError("ERR_JOB_REQUEST_NOT_FOUND",
                       "No job request with id %s." % job_request_id)
    pool = domain.candidate_pool(job_request, slot_kind, referral_kind)
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_REGISTRANT",
                       "No eligible registrant for this slot.")
    return ok(services.dispatch_order_payload(job_request, pool))


# --------------------------------------------------------------------------
# §3.6 referral issuance
# --------------------------------------------------------------------------
def _registration_of_member(member_id):
    """The member's live registration when there is one, else the most recently
    created registration, so the state check at precedence 30 has something to
    report."""
    rows = [r for r in db.registrations.values() if r["member_id"] == member_id]
    if not rows:
        return None
    live = [r for r in rows if r["status"] in ("REGISTERED", "REFERRED")]
    if live:
        live.sort(key=lambda r: (r["created_at"], r["_seq"]))
        return live[-1]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows[-1]


@bp.route("/hiring-hall/job-requests/<job_request_id>/referrals", methods=["POST"])
def issue_referral(job_request_id):
    user_id, role = require("Dispatcher")
    check_pagination_shape()
    data = body()
    slot_kind = s_enum(data, "slot_kind", SLOT_KINDS)
    referral_kind = s_enum(data, "referral_kind", REFERRAL_KINDS)
    expected_version = s_int(data, "expected_job_request_version", minimum=0)
    named_member_id = s_str(data, "member_id", required=False, default=None)
    override_reason = s_str(data, "override_reason", required=False, min_len=None,
                            max_len=500, default=None)

    # 4 — path resource
    job_request = db.job_requests.get(job_request_id)
    if job_request is None:
        raise ApiError("ERR_JOB_REQUEST_NOT_FOUND",
                       "No job request with id %s." % job_request_id)
    if referral_kind == "NAMED_CALL" and named_member_id is None:
        raise ApiError("ERR_INVALID_REQUEST",
                       "A NAMED_CALL referral requires an explicit member_id.")

    # 5 — body foreign key
    member = None
    if named_member_id is not None:
        member = db.members.get(named_member_id)
        if member is None:
            raise ApiError("ERR_MEMBER_NOT_FOUND",
                           "No member with id %s." % named_member_id)

    # 8 — suspension by contractor delinquency
    if job_request["status"] == "SUSPENDED":
        raise ApiError("ERR_JOB_REQUEST_SUSPENDED",
                       "The job request is suspended by contractor delinquency.")

    # 9 — openness and the matching open-slot counter
    if job_request["status"] not in ("OPEN", "PARTIALLY_FILLED"):
        raise ApiError("ERR_JOB_REQUEST_NOT_OPEN",
                       "A %s job request accepts no referrals." % job_request["status"])
    if domain.open_slots_for(job_request, slot_kind) < 1:
        raise ApiError("ERR_JOB_REQUEST_NOT_OPEN",
                       "No open %s slot remains on this request." % slot_kind)

    # 11 — the named member holds no outstanding referral
    if member is not None and domain.member_has_outstanding_referral(named_member_id):
        raise ApiError("ERR_REFERRAL_ALREADY_OUTSTANDING",
                       "The member already holds an outstanding referral.")

    # 15 — the pinned version
    if expected_version != job_request["version"]:
        raise ApiError("ERR_STALE_JOB_REQUEST_VERSION",
                       "The job request has advanced to version %d."
                       % job_request["version"])

    if member is not None:
        # 17 — standing and dispatch eligibility
        if member["standing"] != "GOOD_STANDING" or not domain.member_dispatch_eligible(member):
            raise ApiError("ERR_MEMBER_NOT_IN_GOOD_STANDING",
                           "The member is not dispatch eligible.")
        # 18 — classification against the slot
        if member["classification"] != slot_kind:
            raise ApiError("ERR_CLASSIFICATION_MISMATCH",
                           "A %s slot cannot be filled by a %s."
                           % (slot_kind, member["classification"]))
        # 19 — the special-skill endorsement
        if referral_kind == "SPECIAL_SKILL" and not domain.has_valid_endorsement(
                named_member_id, job_request["required_skill_code"]):
            raise ApiError("ERR_SKILL_ENDORSEMENT_MISSING",
                           "The member holds no verified, unexpired endorsement.")

    # 23 — a named call must have been declared by the contractor
    if referral_kind == "NAMED_CALL":
        if named_member_id not in job_request["named_call_member_ids"]:
            raise ApiError("ERR_NAMED_CALL_NOT_DECLARED",
                           "The contractor did not name this member.")

    # 30 — the target registration must be REGISTERED
    registration = None
    if member is not None:
        registration = _registration_of_member(named_member_id)
        if registration is None or registration["status"] != "REGISTERED":
            raise ApiError("ERR_REGISTRATION_NOT_ACTIVE",
                           "The member holds no active registration.")

    # 35 / 36 — the ratio schedule and the consumption test
    if slot_kind == "APPRENTICE":
        policy = domain.governing_ratio_policy()
        if policy is None:
            raise ApiError("ERR_NO_ACTIVE_RATIO_POLICY",
                           "No apprentice-ratio policy is in force.")
        cap = domain.apprentice_cap(job_request, policy)
        committed = domain.count_referrals(job_request["id"], "APPRENTICE",
                                           ("ISSUED", "ACCEPTED"))
        limit = min(cap, job_request["apprentices_requested"])
        if committed + 1 > limit:
            raise ApiError("ERR_APPRENTICE_RATIO_EXCEEDED",
                           "The apprentice ratio cap permits at most %d apprentices."
                           % limit)

    pool = []
    out_of_order = False
    variant = "NOT_APPLICABLE"
    if referral_kind != "NAMED_CALL":
        pool = domain.candidate_pool(job_request, slot_kind, referral_kind)
        variant = domain.variant_for(job_request)
        # 37 — naming somebody other than rank one needs a written reason
        if member is not None:
            top = pool[0] if pool else None
            if top is None or top["id"] != registration["id"]:
                if override_reason is None or not override_reason.strip():
                    raise ApiError("ERR_OUT_OF_ORDER_DISPATCH",
                                   "The named member is not the top-ranked candidate.")
                out_of_order = True
        # 38 — the pool must not be empty
        if not pool:
            raise ApiError("ERR_NO_ELIGIBLE_REGISTRANT",
                           "No eligible registrant for this slot.")
        if registration is None:
            registration = pool[0]

    clock = now()
    snapshot = {
        "variant_applied": variant,
        "override_reason": override_reason,
        "referral_kind": referral_kind,
        "slot_kind": slot_kind,
        "candidates": domain.candidate_snapshot(pool),
    }
    referral = {
        "id": new_id(),
        "job_request_id": job_request["id"],
        "registration_id": registration["id"],
        "member_id": registration["member_id"],
        "slot_kind": slot_kind,
        "referral_kind": referral_kind,
        "variant_applied": variant,
        "out_of_order_override": out_of_order,
        "override_reason": override_reason,
        "issued_by_user_id": user_id,
        "issued_at": clock,
        "acceptance_deadline": clock + hours(ACCEPTANCE_WINDOW_HOURS),
        "list_position_at_issue": (None if referral_kind == "NAMED_CALL"
                                   else domain.position_number(registration)),
        "refusal_good_cause_code": None,
        "status": "ISSUED",
        "created_at": clock,
        "updated_at": clock,
        "version": 1,
        "_seq": db.seq(),
    }
    db.referrals[referral["id"]] = referral
    registration["status"] = "REFERRED"
    touch(registration)
    touch(job_request)
    services.append_ledger("REFERRAL_ISSUED", referral["member_id"], referral["id"],
                           snapshot=snapshot)
    return created(S.referral_view(referral))
