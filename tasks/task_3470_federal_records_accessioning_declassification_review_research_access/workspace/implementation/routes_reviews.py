"""DeclassReview + EquityReferral endpoints (PRD §3.5).

POST /records/declass-reviews                   ProcessingArchivist (SYSTEMATIC)
                                                or Researcher (MANDATORY), 201
GET  /records/declass-reviews                   all roles except Anonymous
GET  /records/declass-reviews/{id}              all roles except Anonymous
POST /records/declass-reviews/{id}/begin        DeclassReviewer
POST /records/declass-reviews/{id}/referrals    DeclassReviewer (bulk, atomic), 201
POST /records/declass-reviews/{id}/complete     DeclassReviewer
GET  /records/equity-referrals                  all roles except Anonymous
GET  /records/equity-referrals/{id}             all roles except Anonymous
POST /records/equity-referrals/{id}/respond     AgencyLiaison
"""
from flask import Blueprint, request

import calcs
import constants as C
from envelope import ok_array, ok_list, ok_object
from errors import err
from helpers import (
    bump,
    get_collection,
    get_referral,
    get_review,
    load_researcher,
    recompute_posture,
    require_active_researcher,
)
from store import DB, new_id, parse_dt, ts3, tsc
from validation import (
    body_fk,
    get_auth,
    get_body,
    list_page,
    opt_str,
    req_enum,
    req_list_str,
    require_ownership,
    require_role,
)

bp = Blueprint("reviews", __name__)


@bp.post("/records/declass-reviews")
def create_review():
    uid, role = get_auth()                                   # rung 1
    require_role(role, ["ProcessingArchivist", "Researcher"])  # rung 2 (base)
    body = get_body()
    review_type = req_enum(body, "review_type", C.REVIEW_TYPES)
    # flavour-specific role admission (PRD §3.5)
    if review_type == "SYSTEMATIC" and role != "ProcessingArchivist":
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "SYSTEMATIC reviews are opened by ProcessingArchivist",
        )
    if review_type == "MANDATORY" and role != "Researcher":
        raise err(
            "ERR_FORBIDDEN_ROLE",
            "MANDATORY reviews are opened by Researcher",
        )
    # rung 4: body FK existence in declared input order (collection_id first)
    collection_id = body_fk(body, "collection_id")
    collection = get_collection(collection_id)
    requester = None
    if review_type == "MANDATORY":
        requester_id = body.get("requester_researcher_id")
        if not isinstance(requester_id, str) or requester_id == "":
            raise err(
                "ERR_INVALID_REQUEST",
                "requester_researcher_id is required for MANDATORY reviews",
            )
        requester = load_researcher(requester_id)   # 404 + lazy expiry
        require_ownership(uid, requester_id)        # rung 5
    # rung 7 (OCC): after existence and ownership, before any business gate
    ecv = body.get("expected_collection_version")
    if isinstance(ecv, bool) or not isinstance(ecv, int):
        raise err(
            "ERR_INVALID_REQUEST",
            "expected_collection_version is required and must be an integer",
        )
    if ecv != collection["version"]:
        raise err(
            "ERR_STALE_COLLECTION_VERSION",
            "expected_collection_version does not match the collection's "
            "current version",
        )
    # rung 9: researcher active-status (MANDATORY only)
    if review_type == "MANDATORY":
        require_active_researcher(requester)
    # rung 12: at most one OPEN/IN_PROGRESS review per collection
    if any(
        r["collection_id"] == collection["id"] and r["status"] in ("OPEN", "IN_PROGRESS")
        for r in DB.reviews.values()
    ):
        raise err(
            "ERR_REVIEW_ALREADY_OPEN",
            "collection already has a review in OPEN or IN_PROGRESS",
        )
    # rung 13: systematic-review age gate (inclusive 25-year boundary)
    if review_type == "SYSTEMATIC":
        age = calcs.records_age_years(
            DB.now(), parse_dt(collection["records_cutoff_date"])
        )
        if age < C.SYSTEMATIC_REVIEW_AGE_YEARS:
            raise err(
                "ERR_SYSTEMATIC_REVIEW_PREMATURE",
                "records have not reached the 25-year systematic-review age",
            )
    # rung 15: the collection must actually require review
    if collection["restriction_posture"] != "CLASSIFIED_REVIEW_REQUIRED":
        raise err(
            "ERR_COLLECTION_NOT_RESTRICTED",
            "declassification review requires restriction_posture "
            "CLASSIFIED_REVIEW_REQUIRED",
        )
    justification = None
    if review_type == "MANDATORY":
        justification = body.get("justification")
        if not isinstance(justification, str) or justification == "":
            raise err(
                "ERR_INVALID_REQUEST",
                "justification is required for MANDATORY reviews",
            )
    now = ts3(DB.now())
    review = {
        "id": new_id(),
        "collection_id": collection_id,
        "review_type": review_type,
        "requester_researcher_id": (
            requester["id"] if review_type == "MANDATORY" else None
        ),
        "justification": justification if review_type == "MANDATORY" else None,
        "status": "OPEN",
        "lead_reviewer_id": None,
        "reviewer_assessment": None,
        "exemption_codes": [],
        "outcome": None,
        "completed_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    DB.reviews[review["id"]] = review
    # opening a review records review demand against the collection
    bump(collection)
    return ok_object(review, 201)


@bp.get("/records/declass-reviews")
def list_reviews():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("collection_id", "requester_researcher_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.reviews.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/declass-reviews/<review_id>")
def get_one_review(review_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_review(review_id))


@bp.post("/records/declass-reviews/<review_id>/begin")
def begin_review(review_id):
    uid, role = get_auth()
    require_role(role, ["DeclassReviewer"])
    r = get_review(review_id)                     # rung 3
    if r["status"] != "OPEN":                     # rung 8
        raise err("ERR_INVALID_STATE", "begin requires status OPEN")
    r["status"] = "IN_PROGRESS"
    r["lead_reviewer_id"] = uid
    bump(r)
    return ok_object(r)


@bp.post("/records/declass-reviews/<review_id>/referrals")
def create_referrals(review_id):
    _uid, role = get_auth()
    require_role(role, ["DeclassReviewer"])
    review = get_review(review_id)                # rung 3
    body = get_body()
    agency_ids = req_list_str(body, "agency_ids", nonempty=True)
    # rung 4: every referred agency must exist (atomic abort)
    for aid in agency_ids:
        if aid not in DB.agencies:
            raise err("ERR_AGENCY_NOT_FOUND", "agency not found: %s" % aid)
    # rung 8: parent review must be IN_PROGRESS
    if review["status"] != "IN_PROGRESS":
        raise err(
            "ERR_REVIEW_NOT_IN_PROGRESS",
            "referrals may be issued only while the review is IN_PROGRESS",
        )
    # rung 12: no duplicates within the list or against existing referrals
    if len(set(agency_ids)) != len(agency_ids):
        raise err("ERR_DUPLICATE_REFERRAL", "agency_ids contains a duplicate")
    existing = {(r["review_id"], r["agency_id"]) for r in DB.referrals.values()}
    if any((review["id"], aid) in existing for aid in agency_ids):
        raise err(
            "ERR_DUPLICATE_REFERRAL",
            "a referral already exists for this review and agency",
        )
    # atomic: all checks passed, now create
    now_dt = DB.now()
    now3 = ts3(now_dt)
    due = tsc(calcs.add_days(now_dt, C.REFERRAL_RESPONSE_DAYS))
    created = []
    for aid in agency_ids:
        ref = {
            "id": new_id(),
            "review_id": review["id"],
            "agency_id": aid,
            "sent_at": tsc(now_dt),
            "response_due_at": due,
            "status": "SENT",
            "decision": None,
            "exemption_code": None,
            "responded_at": None,
            "created_at": now3,
            "updated_at": now3,
            "version": 1,
        }
        DB.referrals[ref["id"]] = ref
        created.append(ref)
    return ok_array(created, 201)


@bp.post("/records/declass-reviews/<review_id>/complete")
def complete_review(review_id):
    _uid, role = get_auth()
    require_role(role, ["DeclassReviewer"])
    review = get_review(review_id)                # rung 3
    if review["status"] != "IN_PROGRESS":         # rung 8
        raise err(
            "ERR_REVIEW_NOT_IN_PROGRESS",
            "complete requires status IN_PROGRESS",
        )
    # every referral must be RESPONDED or overdue (clock STRICTLY later than
    # response_due_at; at exactly the due instant it still blocks)
    now_dt = DB.now()
    referrals = [r for r in DB.referrals.values() if r["review_id"] == review["id"]]
    for ref in referrals:
        if ref["status"] == "SENT" and not (
            now_dt > parse_dt(ref["response_due_at"])
        ):
            raise err(
                "ERR_REFERRALS_OUTSTANDING",
                "a referral is still SENT and not yet overdue",
            )
    # rung 15 shape
    body = get_body()
    assessment = req_enum(body, "reviewer_assessment", C.REVIEWER_ASSESSMENTS)
    exemption_code = opt_str(body, "exemption_code")
    if assessment == "EXEMPT" and not exemption_code:
        raise err(
            "ERR_EXEMPTION_REQUIRED",
            "an EXEMPT reviewer assessment requires an exemption_code",
        )
    outcome = calcs.declass_review_outcome(assessment, referrals)
    codes = set()
    if assessment == "EXEMPT":
        codes.add(exemption_code)
    for ref in referrals:
        if (
            ref["status"] == "RESPONDED"
            and ref["decision"] == "EXEMPT"
            and ref.get("exemption_code")
        ):
            codes.add(ref["exemption_code"])
    review["reviewer_assessment"] = assessment
    review["exemption_codes"] = sorted(codes)
    review["outcome"] = outcome
    review["completed_at"] = tsc(now_dt)
    review["status"] = "COMPLETED"
    bump(review)
    # cascade into the collection in the same transaction
    collection = DB.collections[review["collection_id"]]
    if outcome == "DECLASSIFIED":
        collection["classification_level"] = "NONE"
    collection["declass_outcome"] = outcome
    recompute_posture(collection)   # fires the §2.8 flip cascade into PUBLIC
    bump(collection)
    return ok_object(review)


# --- EquityReferral ------------------------------------------------------------
@bp.get("/records/equity-referrals")
def list_referrals():
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    filters = {}
    for k in ("review_id", "agency_id", "status"):
        v = request.args.get(k)
        if v is not None:
            filters[k] = v
    page, total, limit, offset = list_page(DB.referrals.values(), filters)
    return ok_list(page, total, limit, offset)


@bp.get("/records/equity-referrals/<referral_id>")
def get_one_referral(referral_id):
    _uid, role = get_auth()
    require_role(role, C.ALL_READ_ROLES)
    return ok_object(get_referral(referral_id))


@bp.post("/records/equity-referrals/<referral_id>/respond")
def respond_referral(referral_id):
    uid, role = get_auth()
    require_role(role, ["AgencyLiaison"])
    ref = get_referral(referral_id)               # rung 3
    require_ownership(uid, ref["agency_id"])      # rung 5
    review = DB.reviews[ref["review_id"]]
    if review["status"] != "IN_PROGRESS":         # rung 8
        raise err(
            "ERR_REVIEW_NOT_IN_PROGRESS",
            "the parent review must be IN_PROGRESS",
        )
    if ref["status"] != "SENT":                   # rung 8 (endpoint-specific)
        raise err(
            "ERR_REFERRAL_ALREADY_RESPONDED",
            "respond requires referral status SENT",
        )
    body = get_body()                             # rung 15
    decision = req_enum(body, "decision", C.REFERRAL_DECISIONS)
    exemption_code = opt_str(body, "exemption_code")
    if decision == "EXEMPT" and not exemption_code:
        raise err(
            "ERR_EXEMPTION_REQUIRED",
            "an EXEMPT referral response requires an exemption_code",
        )
    ref["status"] = "RESPONDED"
    ref["decision"] = decision
    ref["exemption_code"] = exemption_code if decision == "EXEMPT" else None
    ref["responded_at"] = tsc(DB.now())
    bump(ref)
    return ok_object(ref)
