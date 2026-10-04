"""Partnership side: partner colleges, mentors, agreements (OCC-guarded),
outcome readout, and renewal review (PRD 3.3, 3.9)."""

from constants import (
    COHORT_SIZE_MAX,
    COHORT_SIZE_MIN,
    RENEWAL_DECISIONS,
    RENEWAL_MIN_GRADUATION_BPS,
    RENEWAL_MIN_RETENTION_BPS,
)
from core import add, store, touch
from errors import (
    ApiError,
    ERR_ACTIVE_AGREEMENT_EXISTS,
    ERR_COLLEGE_NOT_ACTIVE,
    ERR_COHORT_SIZE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_RENEWAL_THRESHOLDS_NOT_MET,
    ERR_STALE_VERSION,
)
from flask import Blueprint, request
from response import ok
from serialize import pub
from services import outcome_rates
from validate import (
    apply_page,
    auth,
    body,
    lookup,
    page_args,
    req_enum,
    req_int,
    req_str,
    require_role,
)

bp_partnership = Blueprint("partnership", __name__)


# ---------------------------------------------------------------------------
# Partner colleges
# ---------------------------------------------------------------------------

@bp_partnership.post("/api/partner-colleges")
def create_college():
    _uid, role = auth()
    data = body()
    name = req_str(data, "name")
    require_role(role, ["ProgramAdmin"])
    c = add(
        store.colleges,
        {"name": name, "status": "ACTIVE", "renewed_cycles_count": 0},
    )
    return ok(pub(c), 201)


@bp_partnership.get("/api/partner-colleges/<cid>")
def get_college(cid):
    auth()
    return ok(pub(lookup(store.colleges, cid)), 200)


@bp_partnership.get("/api/partner-colleges/<cid>/outcomes")
def get_college_outcomes(cid):
    auth()
    c = lookup(store.colleges, cid)
    r_census, g_census = outcome_rates(cid, "census")
    r_rolling, g_rolling = outcome_rates(cid, "rolling")
    return ok(
        {
            "retention_bps_census": r_census,
            "graduation_bps_census": g_census,
            "retention_bps_rolling": r_rolling,
            "graduation_bps_rolling": g_rolling,
            "college_status": c["status"],
        },
        200,
    )


@bp_partnership.get("/api/partner-colleges/<cid>/agreements")
def list_college_agreements(cid):
    auth()
    limit, offset = page_args()
    lookup(store.colleges, cid)
    items = [a for a in store.agreements.values() if a["partner_college_id"] == cid]
    st = request.args.get("status")
    if st is not None:
        items = [a for a in items if a["status"] == st]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(a) for a in page], 200, meta)


@bp_partnership.get("/api/partner-colleges/<cid>/mentors")
def list_college_mentors(cid):
    auth()
    limit, offset = page_args()
    lookup(store.colleges, cid)
    items = [m for m in store.mentors.values() if m["partner_college_id"] == cid]
    items.sort(key=lambda e: e["_seq"])
    page, meta = apply_page(items, limit, offset)
    return ok([pub(m) for m in page], 200, meta)


@bp_partnership.post("/api/partner-colleges/<cid>/renewal-review")
def renewal_review(cid):
    _uid, role = auth()
    data = body()
    decision = req_enum(data, "decision", RENEWAL_DECISIONS)
    require_role(role, ["ProgramAdmin"])
    c = lookup(store.colleges, cid)
    if c["status"] == "LAPSED":
        raise ApiError(ERR_INVALID_STATE, 409, "LAPSED is terminal")
    if decision == "RENEW":
        # Tier 12: census thresholds; null rates fail the gate.
        r_census, g_census = outcome_rates(cid, "census")
        if (
            r_census is None
            or g_census is None
            or r_census < RENEWAL_MIN_RETENTION_BPS
            or g_census < RENEWAL_MIN_GRADUATION_BPS
        ):
            raise ApiError(
                ERR_RENEWAL_THRESHOLDS_NOT_MET,
                422,
                "Census retention/graduation below the renewal thresholds",
            )
        c["renewed_cycles_count"] += 1
        c["status"] = "ACTIVE"
        touch(c)
    else:  # LAPSE
        c["status"] = "LAPSED"
        touch(c)
        for a in store.agreements.values():
            if a["partner_college_id"] == cid and a["status"] == "DRAFT":
                a["status"] = "EXPIRED"
                touch(a)
    return ok(pub(c), 200)


# ---------------------------------------------------------------------------
# Mentors
# ---------------------------------------------------------------------------

@bp_partnership.post("/api/mentors")
def create_mentor():
    _uid, role = auth()
    data = body()
    college_id = req_str(data, "partner_college_id")
    full_name = req_str(data, "full_name")
    require_role(role, ["ProgramAdmin"])
    lookup(store.colleges, college_id)
    m = add(store.mentors, {"partner_college_id": college_id, "full_name": full_name})
    return ok(pub(m), 201)


# ---------------------------------------------------------------------------
# Partner agreements (drafting is OCC-guarded by expected_college_version)
# ---------------------------------------------------------------------------

@bp_partnership.post("/api/partner-agreements")
def create_agreement():
    _uid, role = auth()
    data = body()
    college_id = req_str(data, "partner_college_id")
    cycle = req_str(data, "admissions_cycle")
    cohort_size = req_int(data, "cohort_size")
    tuition = req_int(data, "tuition_annual_cents")
    if tuition <= 0:
        raise ApiError(
            ERR_INVALID_REQUEST, 400, "tuition_annual_cents must be a positive integer"
        )
    expected = req_int(data, "expected_college_version")
    require_role(role, ["ProgramAdmin"])
    college = lookup(store.colleges, college_id)
    # Tier 7: optimistic concurrency on the college's version.
    if expected != college["version"]:
        raise ApiError(
            ERR_STALE_VERSION,
            412,
            "expected_college_version does not match the college's current version",
        )
    # Tier 8: drafting against a LAPSED college is blocked (PROBATION is allowed).
    if college["status"] == "LAPSED":
        raise ApiError(
            ERR_COLLEGE_NOT_ACTIVE, 409, "Cannot draft agreements for a LAPSED college"
        )
    # Tier 10(i): cohort_size bounds live here, not in request shape.
    if cohort_size < COHORT_SIZE_MIN or cohort_size > COHORT_SIZE_MAX:
        raise ApiError(
            ERR_COHORT_SIZE_INVALID, 422, "cohort_size must be within [3, 6]"
        )
    # Side effect: a new draft supersedes existing DRAFTs for (college, cycle).
    for a in store.agreements.values():
        if (
            a["partner_college_id"] == college_id
            and a["admissions_cycle"] == cycle
            and a["status"] == "DRAFT"
        ):
            a["status"] = "SUPERSEDED"
            touch(a)
    ag = add(
        store.agreements,
        {
            "partner_college_id": college_id,
            "admissions_cycle": cycle,
            "cohort_size": cohort_size,
            "tuition_annual_cents": tuition,
            "status": "DRAFT",
        },
    )
    touch(college)  # drafting increments the college's version by exactly 1
    return ok(pub(ag), 201)


@bp_partnership.post("/api/partner-agreements/<aid>/activate")
def activate_agreement(aid):
    _uid, role = auth()
    require_role(role, ["ProgramAdmin"])
    ag = lookup(store.agreements, aid)
    if ag["status"] != "DRAFT":
        raise ApiError(
            ERR_INVALID_STATE, 409, "Only a DRAFT agreement can be activated"
        )
    college = store.colleges[ag["partner_college_id"]]
    if college["status"] != "ACTIVE":
        raise ApiError(
            ERR_COLLEGE_NOT_ACTIVE,
            409,
            "Agreement activation requires an ACTIVE college",
        )
    for other in store.agreements.values():
        if (
            other["id"] != ag["id"]
            and other["partner_college_id"] == ag["partner_college_id"]
            and other["admissions_cycle"] == ag["admissions_cycle"]
            and other["status"] == "ACTIVE"
        ):
            raise ApiError(
                ERR_ACTIVE_AGREEMENT_EXISTS,
                409,
                "Another ACTIVE agreement exists for this college and cycle",
            )
    ag["status"] = "ACTIVE"
    touch(ag)
    return ok(pub(ag), 200)
