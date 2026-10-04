"""Placement offers: create, read, accept, decline (PRD 3.5)."""

from constants import TRAINING_CATEGORY, TRAINING_MODULES
from core import add, store, touch
from errors import (
    ApiError,
    ERR_ACTIVE_OFFER_EXISTS,
    ERR_CITY_MISMATCH,
    ERR_COHORT_FULL,
    ERR_COHORT_NOT_FORMING,
    ERR_FORBIDDEN,
    ERR_INVALID_STATE,
)
from flask import Blueprint, request
from ledger import has_live_offer, seat_counts
from response import ok
from serialize import pub
from services import create_offer, run_promotion_sweep
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    req_str,
    require_role,
)

bp_offers = Blueprint("offers", __name__)


@bp_offers.post("/api/offers")
def create_offer_endpoint():
    _uid, role = auth()
    data = body()
    nominee_id = req_str(data, "nominee_id")
    cohort_id = req_str(data, "cohort_id")
    require_role(role, ["SelectionOfficer", "ProgramAdmin"])
    n = lookup(store.nominees, nominee_id)
    cohort = lookup(store.cohorts, cohort_id)
    # Tier 8, nominee state first, then cohort state.
    if n["status"] != "SELECTED":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Offer creation requires a SELECTED nominee"
        )
    if cohort["status"] != "FORMING":
        raise ApiError(
            ERR_COHORT_NOT_FORMING, 409, "Offer creation requires a FORMING cohort"
        )
    # Tier 10(b): one live offer per nominee across all cohorts.
    if has_live_offer(nominee_id):
        raise ApiError(
            ERR_ACTIVE_OFFER_EXISTS,
            409,
            "Nominee already holds an OFFERED or ACCEPTED offer",
        )
    # Tier 10(e): city match.
    if n["city_program_id"] != cohort["city_program_id"]:
        raise ApiError(
            ERR_CITY_MISMATCH,
            422,
            "Nominee's city program differs from the cohort's",
        )
    # Tier 11: capacity.
    committed, outstanding = seat_counts(cohort_id)
    if cohort["cohort_size"] - committed - outstanding <= 0:
        raise ApiError(ERR_COHORT_FULL, 422, "Cohort has no seats remaining")
    offer = create_offer(n, cohort)
    return ok(pub(offer), 201)


@bp_offers.get("/api/offers")
def list_offers():
    auth()
    limit, offset = page_args()
    items = list(store.offers.values())
    for param in ("nominee_id", "cohort_id", "status"):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[param] == v]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(o) for o in page], 200, meta)


@bp_offers.get("/api/offers/<oid>")
def get_offer(oid):
    auth()
    return ok(pub(lookup(store.offers, oid)), 200)


@bp_offers.post("/api/offers/<oid>/accept")
def accept_offer(oid):
    uid, role = auth()
    require_role(role, ["Nominee"])
    offer = lookup(store.offers, oid)
    if offer["nominee_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "A nominee may answer only its own offers")
    if offer["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OFFERED offer can be accepted")
    cohort = store.cohorts[offer["cohort_id"]]
    nominee = store.nominees[offer["nominee_id"]]
    offer["status"] = "ACCEPTED"
    touch(offer)
    scholar = add(
        store.scholars,
        {
            "cohort_id": cohort["id"],
            "nominee_id": nominee["id"],
            "enrollment_status": "PRE_COLLEGIATE",
            "standing": "GOOD_STANDING",
            "ever_matriculated": False,
        },
    )
    for code in TRAINING_MODULES:
        add(
            store.training_records,
            {
                "scholar_id": scholar["id"],
                "module_code": code,
                "category": TRAINING_CATEGORY[code],
                "status": "NOT_STARTED",
                "completed_at": None,
            },
        )
    nominee["status"] = "PLACED"
    touch(nominee)
    touch(cohort)  # seats_committed +1, offers_outstanding -1
    committed, _ = seat_counts(cohort["id"])
    if committed >= cohort["cohort_size"]:  # boundary inclusive: == locks
        cohort["status"] = "LOCKED"
        touch(cohort)
    return ok(pub(offer), 200)


@bp_offers.post("/api/offers/<oid>/decline")
def decline_offer(oid):
    uid, role = auth()
    require_role(role, ["Nominee"])
    offer = lookup(store.offers, oid)
    if offer["nominee_id"] != uid:
        raise ApiError(ERR_FORBIDDEN, 403, "A nominee may answer only its own offers")
    if offer["status"] != "OFFERED":
        raise ApiError(ERR_INVALID_STATE, 409, "Only an OFFERED offer can be declined")
    offer["status"] = "DECLINED"
    touch(offer)
    cohort = store.cohorts[offer["cohort_id"]]
    touch(cohort)  # offers_outstanding -1
    run_promotion_sweep(cohort)
    return ok(pub(offer), 200)
