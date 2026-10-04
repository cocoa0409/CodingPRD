"""Recruitment pipeline: city programs, nominating partners, nominees,
decisions, withdrawals, and assessor evaluations (PRD 3.1, 3.2)."""

from constants import (
    DECISIONS,
    DIMENSION_FLOOR,
    FLOOR_CAP_SCORE,
    NOMINATION_QUOTA_MAX,
    NOMINATION_QUOTA_MIN,
    PARTNER_KINDS,
    REQUIRED_EVALUATIONS_PER_ROUND,
    ROUND_CUTOFFS,
    W_GROUP_PRESENCE,
    W_LEADERSHIP,
    W_TEAMWORK,
)
from core import add, now, rhu, store, touch
from errors import (
    ApiError,
    ERR_CUTOFF_NOT_MET,
    ERR_DUPLICATE_EVALUATION,
    ERR_FORBIDDEN,
    ERR_INSUFFICIENT_EVALUATIONS,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_NOMINATION_QUOTA_EXCEEDED,
    ERR_NOMINATION_WINDOW_CLOSED,
    ERR_NOMINEE_NOT_IN_ROUND,
)
from flask import Blueprint, request
from ledger import nominations_used, round_evals
from response import ok
from serialize import partner_out, pub
from services import revoke_pending_offers_of_nominee
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    req_dt,
    req_enum,
    req_int,
    req_str,
    require_role,
)

bp_recruitment = Blueprint("recruitment", __name__)


# ---------------------------------------------------------------------------
# City programs
# ---------------------------------------------------------------------------

@bp_recruitment.post("/api/city-programs")
def create_city_program():
    _uid, role = auth()
    data = body()
    code = req_str(data, "code")
    name = req_str(data, "name")
    cycle = req_str(data, "admissions_cycle")
    opens = req_dt(data, "nomination_window_opens_at")
    closes = req_dt(data, "nomination_window_closes_at")
    require_role(role, ["ProgramAdmin"])
    cp = add(
        store.city_programs,
        {
            "code": code,
            "name": name,
            "admissions_cycle": cycle,
            "nomination_window_opens_at": opens,
            "nomination_window_closes_at": closes,
        },
    )
    return ok(pub(cp), 201)


@bp_recruitment.get("/api/city-programs/<pid>")
def get_city_program(pid):
    auth()
    return ok(pub(lookup(store.city_programs, pid)), 200)


# ---------------------------------------------------------------------------
# Nominating partners
# ---------------------------------------------------------------------------

@bp_recruitment.post("/api/nominating-partners")
def create_partner():
    _uid, role = auth()
    data = body()
    cp_id = req_str(data, "city_program_id")
    name = req_str(data, "name")
    kind = req_enum(data, "kind", PARTNER_KINDS)
    quota = req_int(data, "nomination_quota")
    if quota < NOMINATION_QUOTA_MIN or quota > NOMINATION_QUOTA_MAX:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "nomination_quota must be between 1 and 20"
        )
    require_role(role, ["ProgramAdmin"])
    lookup(store.city_programs, cp_id)
    p = add(
        store.partners,
        {
            "city_program_id": cp_id,
            "name": name,
            "kind": kind,
            "nomination_quota": quota,
        },
    )
    return ok(partner_out(p), 201)


@bp_recruitment.get("/api/city-programs/<pid>/partners")
def list_partners(pid):
    auth()
    limit, offset = page_args()
    lookup(store.city_programs, pid)
    items = [p for p in store.partners.values() if p["city_program_id"] == pid]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([partner_out(p) for p in page], 200, meta)


# ---------------------------------------------------------------------------
# Nominees
# ---------------------------------------------------------------------------

@bp_recruitment.post("/api/nominees")
def create_nominee():
    uid, role = auth()
    data = body()
    cp_id = req_str(data, "city_program_id")
    full_name = req_str(data, "full_name")
    nominator_id = data.get("nominator_id")
    if nominator_id is not None and not isinstance(nominator_id, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "nominator_id must be a string")
    first_gen = data.get("first_generation", False)
    if not isinstance(first_gen, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "first_generation must be a boolean")
    require_role(role, ["Nominator", "ProgramAdmin"])
    # Tier 4 ownership: a Nominator files under its own partner record; a
    # supplied nominator_id must be absent or equal to X-User-ID.
    if role == "Nominator":
        if nominator_id is not None and nominator_id != uid:
            raise ApiError(
                ERR_FORBIDDEN, 403, "nominator_id does not match the caller"
            )
        effective_nominator = uid
    else:
        if nominator_id is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                400,
                "nominator_id is required for ProgramAdmin callers",
            )
        effective_nominator = nominator_id
    cp = lookup(store.city_programs, cp_id)
    partner = lookup(store.partners, effective_nominator)
    # Tier 9: inclusive nomination window on the nominee's city program.
    t = now()
    if t < cp["nomination_window_opens_at"] or t > cp["nomination_window_closes_at"]:
        raise ApiError(
            ERR_NOMINATION_WINDOW_CLOSED,
            422,
            "Logical now is outside the city program's nomination window",
        )
    # Tier 11: quota.
    if nominations_used(partner["id"]) >= partner["nomination_quota"]:
        raise ApiError(
            ERR_NOMINATION_QUOTA_EXCEEDED,
            422,
            "Nominating partner has no remaining nomination quota",
        )
    n = add(
        store.nominees,
        {
            "city_program_id": cp_id,
            "nominator_id": partner["id"],
            "full_name": full_name,
            "first_generation": first_gen,
            "status": "NOMINATED",
            "current_round": 0,
            "round_1_score": None,
            "round_2_score": None,
            "round_3_score": None,
        },
    )
    touch(partner)  # nominations_used rose by one
    return ok(pub(n), 201)


@bp_recruitment.get("/api/nominees")
def list_nominees():
    auth()
    limit, offset = page_args()
    items = list(store.nominees.values())
    cp = request.args.get("city_program_id")
    nm = request.args.get("nominator_id")
    st = request.args.get("status")
    if cp is not None:
        items = [n for n in items if n["city_program_id"] == cp]
    if nm is not None:
        items = [n for n in items if n["nominator_id"] == nm]
    if st is not None:
        items = [n for n in items if n["status"] == st]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(n) for n in page], 200, meta)


@bp_recruitment.get("/api/nominees/<nid>")
def get_nominee(nid):
    auth()
    return ok(pub(lookup(store.nominees, nid)), 200)


@bp_recruitment.post("/api/nominees/<nid>/withdraw")
def withdraw_nominee(nid):
    uid, role = auth()
    require_role(role, ["Nominator", "ProgramAdmin"])
    n = lookup(store.nominees, nid)
    if role == "Nominator" and n["nominator_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "Nominator may withdraw only its own nominees")
    if n["status"] != "NOMINATED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Withdrawal is only possible from NOMINATED"
        )
    n["status"] = "WITHDRAWN"
    touch(n)
    partner = store.partners.get(n["nominator_id"])
    if partner is not None:
        touch(partner)  # nominations_used fell by one
    return ok(pub(n), 200)


@bp_recruitment.post("/api/nominees/<nid>/decision")
def nominee_decision(nid):
    _uid, role = auth()
    data = body()
    decision = req_enum(data, "decision", DECISIONS)
    require_role(role, ["SelectionOfficer", "ProgramAdmin"])
    n = lookup(store.nominees, nid)
    st = n["status"]
    if decision == "ADVANCE":
        if st == "NOMINATED":
            n["status"] = "ROUND_1"
            n["current_round"] = 1
            touch(n)
        elif st in ("ROUND_1", "ROUND_2", "ROUND_3"):
            rnd = {"ROUND_1": 1, "ROUND_2": 2, "ROUND_3": 3}[st]
            # Tier 12: evaluation-count gate runs before the cutoff gate.
            if len(round_evals(n["id"], rnd)) < REQUIRED_EVALUATIONS_PER_ROUND:
                raise ApiError(
                    ERR_INSUFFICIENT_EVALUATIONS,
                    422,
                    "Fewer than 2 evaluations exist for the current round",
                )
            score = n["round_%d_score" % rnd]
            if score < ROUND_CUTOFFS[rnd]:
                raise ApiError(
                    ERR_CUTOFF_NOT_MET,
                    422,
                    "Round score is below the round cutoff",
                )
            if rnd == 1:
                n["status"] = "ROUND_2"
                n["current_round"] = 2
            elif rnd == 2:
                n["status"] = "ROUND_3"
                n["current_round"] = 3
            else:
                n["status"] = "SELECTED"  # current_round stays 3
            touch(n)
        elif st == "WAITLISTED":
            n["status"] = "SELECTED"
            touch(n)
        else:
            raise ApiError(
                ERR_INVALID_STATE, 409, "ADVANCE is not declared from %s" % st
            )
    elif decision == "WAITLIST":
        if st != "ROUND_3":
            raise ApiError(
                ERR_INVALID_STATE, 409, "WAITLIST is only declared from ROUND_3"
            )
        if len(round_evals(n["id"], 3)) < REQUIRED_EVALUATIONS_PER_ROUND:
            raise ApiError(
                ERR_INSUFFICIENT_EVALUATIONS,
                422,
                "Fewer than 2 evaluations exist for round 3",
            )
        n["status"] = "WAITLISTED"  # no cutoff requirement
        touch(n)
    else:  # DROP
        if st in ("PLACED", "DROPPED", "WITHDRAWN"):
            raise ApiError(
                ERR_INVALID_STATE, 409, "DROP is not declared from %s" % st
            )
        n["status"] = "DROPPED"
        touch(n)
        revoke_pending_offers_of_nominee(n)
    return ok(pub(n), 200)


@bp_recruitment.get("/api/nominees/<nid>/evaluations")
def list_nominee_evaluations(nid):
    auth()
    limit, offset = page_args()
    lookup(store.nominees, nid)
    items = [e for e in store.evaluations.values() if e["nominee_id"] == nid]
    rnd = request.args.get("round_number")
    if rnd is not None:
        items = [e for e in items if str(e["round_number"]) == rnd]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(e) for e in page], 200, meta)


# ---------------------------------------------------------------------------
# Evaluations (immutable: id + created_at only)
# ---------------------------------------------------------------------------

@bp_recruitment.post("/api/evaluations")
def create_evaluation():
    uid, role = auth()
    data = body()
    nominee_id = req_str(data, "nominee_id")
    round_number = req_int(data, "round_number")
    leadership = req_int(data, "leadership")
    teamwork = req_int(data, "teamwork")
    group_presence = req_int(data, "group_presence")
    if round_number not in (1, 2, 3):
        raise ApiError(ERR_INVALID_REQUEST, 400, "round_number must be 1, 2, or 3")
    for dim in ("leadership", "teamwork", "group_presence"):
        v = data[dim]
        if v < 0 or v > 100:
            raise ApiError(
                ERR_INVALID_REQUEST, 400, "%s must be between 0 and 100" % dim
            )
    require_role(role, ["Assessor"])
    n = lookup(store.nominees, nominee_id)
    # Tier 8: nominee must be in the matching round at submission.
    if n["status"] != "ROUND_%d" % round_number:
        raise ApiError(
            ERR_NOMINEE_NOT_IN_ROUND,
            409,
            "Nominee is not currently in round %d" % round_number,
        )
    # Tier 10(a): uniqueness of (nominee_id, round_number, assessor_ref).
    for e in store.evaluations.values():
        if (
            e["nominee_id"] == nominee_id
            and e["round_number"] == round_number
            and e["assessor_ref"] == uid
        ):
            raise ApiError(
                ERR_DUPLICATE_EVALUATION,
                409,
                "This assessor already scored this nominee in this round",
            )
    base = (
        W_LEADERSHIP * leadership
        + W_TEAMWORK * teamwork
        + W_GROUP_PRESENCE * group_presence
    )
    if min(leadership, teamwork, group_presence) < DIMENSION_FLOOR:
        weighted = min(base, FLOOR_CAP_SCORE)
    else:
        weighted = base
    ev = add(
        store.evaluations,
        {
            "nominee_id": nominee_id,
            "round_number": round_number,
            "assessor_ref": uid,
            "leadership": leadership,
            "teamwork": teamwork,
            "group_presence": group_presence,
            "weighted_score": weighted,
        },
        common=False,
    )
    # nominee_round_score: null until >= 2 evaluations, then round-half-up mean.
    evals = round_evals(nominee_id, round_number)
    new_score = None
    if len(evals) >= REQUIRED_EVALUATIONS_PER_ROUND:
        new_score = rhu(sum(e["weighted_score"] for e in evals), len(evals))
    field = "round_%d_score" % round_number
    if n[field] != new_score:
        n[field] = new_score
        touch(n)
    return ok(pub(ev), 201)
