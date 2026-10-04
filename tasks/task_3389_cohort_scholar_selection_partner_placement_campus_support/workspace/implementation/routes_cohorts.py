"""Cohorts: creation, reads, and the four-step matriculation (PRD 3.4, 3.6)."""

from constants import (
    BPS_DENOMINATOR,
    FEE_BASE_CENTS,
    FEE_RATE_BPS,
    TRAINING_TOTAL,
)
from core import add, rhu, store, touch
from errors import (
    ApiError,
    ERR_AGREEMENT_NOT_ACTIVE,
    ERR_COHORT_EXISTS,
    ERR_INVALID_STATE,
    ERR_MENTOR_COLLEGE_MISMATCH,
)
from flask import Blueprint, request
from ledger import accepted_offer_of, training_completed_count
from response import ok
from serialize import cohort_out
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    req_str,
    require_role,
)

bp_cohorts = Blueprint("cohorts", __name__)


@bp_cohorts.post("/api/cohorts")
def create_cohort():
    _uid, role = auth()
    data = body()
    agreement_id = req_str(data, "agreement_id")
    cp_id = req_str(data, "city_program_id")
    mentor_id = req_str(data, "mentor_id")
    require_role(role, ["ProgramAdmin"])
    ag = lookup(store.agreements, agreement_id)
    lookup(store.city_programs, cp_id)
    mentor = lookup(store.mentors, mentor_id)
    # Tier 8: the agreement must be ACTIVE.
    if ag["status"] != "ACTIVE":
        raise ApiError(
            ERR_AGREEMENT_NOT_ACTIVE, 409, "Cohort creation requires an ACTIVE agreement"
        )
    # Tier 10(c): at most one cohort per agreement.
    for c in store.cohorts.values():
        if c["agreement_id"] == agreement_id:
            raise ApiError(ERR_COHORT_EXISTS, 409, "A cohort already exists for this agreement")
    # Tier 10(f): the mentor must belong to the agreement's college.
    if mentor["partner_college_id"] != ag["partner_college_id"]:
        raise ApiError(
            ERR_MENTOR_COLLEGE_MISMATCH,
            422,
            "Mentor does not belong to the agreement's partner college",
        )
    cohort = add(
        store.cohorts,
        {
            "agreement_id": agreement_id,
            "city_program_id": cp_id,
            "partner_college_id": ag["partner_college_id"],
            "mentor_id": mentor_id,
            "cohort_size": ag["cohort_size"],
            "tuition_annual_cents": ag["tuition_annual_cents"],
            "status": "FORMING",
            "invoice_total_cents": None,
        },
    )
    return ok(cohort_out(cohort), 201)


@bp_cohorts.get("/api/cohorts")
def list_cohorts():
    auth()
    limit, offset = page_args()
    items = list(store.cohorts.values())
    for param, field in (
        ("agreement_id", "agreement_id"),
        ("city_program_id", "city_program_id"),
        ("partner_college_id", "partner_college_id"),
        ("mentor_id", "mentor_id"),
        ("status", "status"),
    ):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[field] == v]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([cohort_out(c) for c in page], 200, meta)


@bp_cohorts.get("/api/cohorts/<cid>")
def get_cohort(cid):
    auth()
    return ok(cohort_out(lookup(store.cohorts, cid)), 200)


@bp_cohorts.post("/api/cohorts/<cid>/matriculate")
def matriculate_cohort(cid):
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    cohort = lookup(store.cohorts, cid)
    if cohort["status"] != "LOCKED":
        raise ApiError(ERR_INVALID_STATE, 409, "Matriculation requires a LOCKED cohort")
    # Step 1: move the cohort first; this suppresses every LOCKED->FORMING
    # revert and every promotion sweep for the remainder of the call.
    cohort["status"] = "MATRICULATED"
    touch(cohort)
    # Step 2: expire every still-OFFERED offer in place (no promotion sweep).
    pending = [
        o
        for o in store.offers.values()
        if o["cohort_id"] == cid and o["status"] == "OFFERED"
    ]
    pending.sort(key=lambda o: o["_seq"])
    for o in pending:
        o["status"] = "EXPIRED"
        touch(o)
    if pending:
        touch(cohort)
    # Step 3: per-scholar training gate, in scholar created_at ASC order.
    scholars = [s for s in store.scholars.values() if s["cohort_id"] == cid]
    scholars.sort(key=lambda s: s["_seq"])
    matriculated_now = []
    for s in scholars:
        # Pre-existing MATRICULATED or WITHDRAWN scholars are excluded from the
        # gate (PRD 3.6 invoice input_set): only PRE_COLLEGIATE scholars are
        # visited. Re-applying the gate to a withdrawn scholar would resurrect
        # them and wrongly bill them.
        if s["enrollment_status"] != "PRE_COLLEGIATE":
            continue
        offer = accepted_offer_of(cid, s["nominee_id"])
        if training_completed_count(s["id"]) == TRAINING_TOTAL:
            s["enrollment_status"] = "MATRICULATED"
            s["ever_matriculated"] = True
            touch(s)
            if offer is not None:
                offer["status"] = "FULFILLED"
                touch(offer)
            matriculated_now.append(s)
        else:
            s["enrollment_status"] = "WITHDRAWN"
            touch(s)
            if offer is not None:
                offer["status"] = "REVOKED"
                touch(offer)
            touch(cohort)  # seats_committed fell by one; no revert, no promotion
    # Step 4: program-fee invoice over exactly the scholars matriculated in
    # this call; each per-scholar fee is rounded HALF_UP to whole cents BEFORE
    # summing (PRD 3.6 pinned rounding order). Zero matriculated -> 0.
    total = 0
    for _s in matriculated_now:
        total += FEE_BASE_CENTS + rhu(
            cohort["tuition_annual_cents"] * FEE_RATE_BPS, BPS_DENOMINATOR
        )
    cohort["invoice_total_cents"] = total
    touch(cohort)
    return ok(cohort_out(cohort), 200)
