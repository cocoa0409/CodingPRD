"""Scholars: reads, the two-axis lifecycle, and training completion (PRD 3.7)."""

from constants import (
    ENROLLMENT_STATUSES,
    ENROLLMENT_TRANSITIONS,
    STANDING_VALUES,
    TERMINAL_ENROLLMENT,
)
from core import now, store, touch
from errors import (
    ApiError,
    ERR_FORBIDDEN,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
)
from flask import Blueprint, request
from response import ok
from serialize import pub, scholar_out
from services import check_cohort_completion, withdraw_scholar_pre_collegiate
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    require_role,
)

bp_scholars = Blueprint("scholars", __name__)


@bp_scholars.get("/api/scholars")
def list_scholars():
    auth()
    limit, offset = page_args()
    items = list(store.scholars.values())
    for param in ("cohort_id", "nominee_id", "enrollment_status", "standing"):
        v = request.args.get(param)
        if v is not None:
            items = [s for s in items if s[param] == v]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([scholar_out(s) for s in page], 200, meta)


@bp_scholars.get("/api/scholars/<sid>")
def get_scholar(sid):
    auth()
    return ok(scholar_out(lookup(store.scholars, sid)), 200)


@bp_scholars.get("/api/scholars/<sid>/training-records")
def list_training_records(sid):
    auth()
    limit, offset = page_args()
    lookup(store.scholars, sid)
    items = [t for t in store.training_records.values() if t["scholar_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [t for t in items if t["status"] == st]
    # T1..T8 share a created_at, so this listing sorts by module_code (PRD 2.3).
    items.sort(key=lambda t: t["module_code"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(t) for t in page], 200, meta)


@bp_scholars.get("/api/scholars/<sid>/internships")
def list_scholar_internships(sid):
    auth()
    limit, offset = page_args()
    lookup(store.scholars, sid)
    items = [i for i in store.internships.values() if i["scholar_id"] == sid]
    st = request.args.get("status")
    if st is not None:
        items = [i for i in items if i["status"] == st]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(i) for i in page], 200, meta)


@bp_scholars.post("/api/scholars/<sid>/lifecycle")
def scholar_lifecycle(sid):
    uid, role = auth()
    data = body()
    to_enr = data.get("to_enrollment_status")
    to_std = data.get("to_standing")
    if to_enr is None and to_std is None:
        raise ApiError(
            ERR_INVALID_REQUEST,
            400,
            "At least one of to_enrollment_status / to_standing is required",
        )
    if to_enr is not None and (not isinstance(to_enr, str) or to_enr not in ENROLLMENT_STATUSES):
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "to_enrollment_status is not a declared value"
        )
    if to_std is not None and (not isinstance(to_std, str) or to_std not in STANDING_VALUES):
        raise ApiError(ERR_INVALID_REQUEST, 400, "to_standing is not a declared value")
    require_role(role, ["ProgramAdmin", "Scholar"])
    scholar = lookup(store.scholars, sid)
    # Tier 4 ownership: a Scholar caller drives only its own record and only
    # toward self-withdrawal.
    if role == "Scholar":
        if scholar["id"] != uid or to_enr != "WITHDRAWN" or to_std is not None:
            raise ApiError(
                ERR_FORBIDDEN,
                403,
                "A scholar may only withdraw itself (to_enrollment_status=WITHDRAWN)",
            )
    cur = scholar["enrollment_status"]
    # Validate the enrollment axis against the current state (tier 8).
    new_enr = cur
    if to_enr is not None:
        if to_enr not in ENROLLMENT_TRANSITIONS.get(cur, []):
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "enrollment_status %s -> %s is not a declared transition" % (cur, to_enr),
            )
        new_enr = to_enr
    # Validate the standing axis against the post-enrollment state: standing
    # freezes once enrollment_status is terminal (PRD 3.7).
    if to_std is not None:
        if new_enr in TERMINAL_ENROLLMENT:
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "standing is frozen once enrollment_status is terminal",
            )
        if to_std == scholar["standing"]:
            raise ApiError(
                ERR_INVALID_STATE,
                409,
                "standing %s -> %s is not a declared transition"
                % (scholar["standing"], to_std),
            )
    # Apply enrollment first, then standing.
    if new_enr != cur:
        scholar["enrollment_status"] = new_enr
        touch(scholar)
        if cur == "PRE_COLLEGIATE" and new_enr == "WITHDRAWN":
            withdraw_scholar_pre_collegiate(scholar)
        elif new_enr in TERMINAL_ENROLLMENT:
            # Post-matriculation terminal transitions run the completion check.
            cohort = store.cohorts.get(scholar["cohort_id"])
            if cohort is not None:
                check_cohort_completion(cohort)
    if to_std is not None and to_std != scholar["standing"]:
        scholar["standing"] = to_std
        touch(scholar)
    return ok(scholar_out(scholar), 200)


@bp_scholars.post("/api/training-records/<tid>/complete")
def complete_training_record(tid):
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    tr = lookup(store.training_records, tid)
    if tr["status"] != "NOT_STARTED":
        raise ApiError(ERR_INVALID_STATE, 409, "Training record is already COMPLETED")
    tr["status"] = "COMPLETED"
    tr["completed_at"] = now()  # logical-clock timestamp (PRD 2.4)
    touch(tr)
    scholar = store.scholars.get(tr["scholar_id"])
    if scholar is not None:
        touch(scholar)  # training_completed_count rose by one
    return ok(pub(tr), 200)
