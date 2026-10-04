"""Collection reviews (PRD 3.6): open (review-kind field pairing), submit
(creator only), decide (chair, OCC, segregation of duties, cultural-property
clearance, fund gates), execute (acquisition posting / deaccession cascade)."""

from flask import Blueprint

import calc
import constants
import db
import serializers
import util
from envelope import listing, success
from errors import fail
from middleware import auth, get_or_404, require_role

bp = Blueprint("collection_reviews", __name__)

REVIEW_READ_ROLES = ["PlatformAdmin", "Registrar", "Curator", "CommitteeChair", "FinanceOfficer"]


@bp.post("/campus/collection-reviews")
def create_review():
    uid, role = auth()
    require_role(role, ["Curator"])
    b = util.body()
    kind = b.get("review_kind")
    # (4) body FK existence for the kind-relevant reference, when provided
    if kind == "ACQUISITION" and b.get("fund_id") is not None:
        get_or_404("funds", b["fund_id"], "FundAccount")
    if kind == "DEACCESSION" and b.get("object_id") is not None:
        get_or_404("collection_objects", b["object_id"], "CollectionObject")
    # (9) request shape and review-kind field pairing
    if kind not in constants.REVIEW_KINDS:
        fail("ERR_INVALID_REQUEST", "review_kind must be ACQUISITION or DEACCESSION")
    if kind == "ACQUISITION":
        fund_id = util.req_str(b, "fund_id")
        proposed_object_title = util.req_str(b, "proposed_object_title")
        estimated_cost_cents = util.req_int(b, "estimated_cost_cents", minimum=1)
        if b.get("object_id") is not None:
            fail("ERR_INVALID_REQUEST", "An ACQUISITION review must carry a null object_id")
        object_id = None
        disposal_method = None
    else:
        object_id = util.req_str(b, "object_id")
        disposal_method = util.req_enum(b, "disposal_method", constants.DISPOSAL_METHODS)
        if b.get("fund_id") is not None:
            fail("ERR_INVALID_REQUEST", "A DEACCESSION review must carry a null fund_id")
        fund_id = None
        proposed_object_title = None
        estimated_cost_cents = None
    cultural_done = util.opt_bool(b, "cultural_property_review_completed", False)
    r = db.new_entity(
        {
            "review_kind": kind,
            "object_id": object_id,
            "fund_id": fund_id,
            "proposed_object_title": proposed_object_title,
            "estimated_cost_cents": estimated_cost_cents,
            "disposal_method": disposal_method,
            "cultural_property_review_completed": cultural_done,
            "status": "DRAFT",
            "submitted_by_user_id": None,
            "decided_by_user_id": None,
            "_creator_user_id": uid,  # internal: gates the submit action
        }
    )
    db.STORE["collection_reviews"][r["id"]] = r
    return success(serializers.collection_review(r), 201)


@bp.get("/campus/collection-reviews")
def list_reviews():
    _uid, role = auth()
    require_role(role, REVIEW_READ_ROLES)
    limit, offset = util.pagination()
    f_object = util.request.args.get("object_id")
    f_fund = util.request.args.get("fund_id")
    rows = []
    for r in db.all_sorted("collection_reviews"):
        if f_object is not None and r["object_id"] != f_object:
            continue
        if f_fund is not None and r["fund_id"] != f_fund:
            continue
        rows.append(r)
    page = rows[offset : offset + limit]
    return listing([serializers.collection_review(r) for r in page], limit, offset, len(rows))


@bp.get("/campus/collection-reviews/<rid>")
def get_review(rid):
    _uid, role = auth()
    require_role(role, REVIEW_READ_ROLES)
    r = get_or_404("collection_reviews", rid, "CollectionReview")
    return success(serializers.collection_review(r))


@bp.post("/campus/collection-reviews/<rid>/submit")
def submit_review(rid):
    uid, role = auth()
    require_role(role, ["Curator"])
    r = get_or_404("collection_reviews", rid, "CollectionReview")
    # Ownership: only the creating curator's X-User-ID may submit.
    if r["_creator_user_id"] != uid:
        fail("ERR_UNAUTHORIZED_ROLE", "Only the review's creator may submit it")
    if r["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT review can be submitted")
    r["status"] = "SUBMITTED"
    r["submitted_by_user_id"] = uid
    db.touch(r)
    return success(serializers.collection_review(r))


@bp.post("/campus/collection-reviews/<rid>/decide")
def decide_review(rid):
    uid, role = auth()
    require_role(role, ["CommitteeChair"])
    r = get_or_404("collection_reviews", rid, "CollectionReview")
    b = util.body()
    # (5) transition legality
    if r["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED review can be decided")
    # OCC on expected_review_version (stale read -> 412)
    ev = b.get("expected_review_version")
    if util.is_int(ev) and ev != r["version"]:
        fail("ERR_STALE_REVIEW_VERSION", "The review version has advanced; re-read and retry")
    outcome_raw = b.get("outcome")
    # (6) the fund must be ACTIVE for an acquisition decision
    if r["review_kind"] == "ACQUISITION":
        fund = db.STORE["funds"].get(r["fund_id"])
        if fund is not None and fund["status"] != "ACTIVE":
            fail("ERR_FUND_FROZEN", "The fund is FROZEN")
    # (7) segregation of duties: no one decides their own submission
    if uid == r["submitted_by_user_id"]:
        fail("ERR_SEGREGATION_OF_DUTIES", "The chair may not decide their own submission")
    # (8) cultural property clearance on a deaccession approval
    if outcome_raw == "APPROVED" and r["review_kind"] == "DEACCESSION":
        obj = db.STORE["collection_objects"].get(r["object_id"])
        if (
            obj is not None
            and obj["is_cultural_property"]
            and not r["cultural_property_review_completed"]
        ):
            fail(
                "ERR_CULTURAL_PROPERTY_REVIEW_PENDING",
                "Cultural-property review must be completed before approval",
            )
    # (9) request shape
    if not util.is_int(ev):
        fail("ERR_INVALID_REQUEST", "Field expected_review_version is required and must be an integer")
    if outcome_raw not in ("APPROVED", "REJECTED"):
        fail("ERR_INVALID_REQUEST", "outcome must be APPROVED or REJECTED")
    if outcome_raw == "APPROVED":
        if r["review_kind"] == "DEACCESSION":
            obj = db.STORE["collection_objects"].get(r["object_id"])
            # (18) an ACTIVE loan blocks approval; in-negotiation/agreed loans
            # are cascade-cancelled at execute instead
            for l in db.STORE["loan_agreements"].values():
                if l["object_id"] == r["object_id"] and l["status"] == "ACTIVE":
                    fail("ERR_OBJECT_ON_ACTIVE_LOAN", "The object is out on an active loan")
            if obj is not None and obj["status"] in ("IN_COLLECTION", "UNDER_CONSERVATION"):
                obj["status"] = "PENDING_DEACCESSION"
                db.touch(obj)
        else:
            fund = db.STORE["funds"].get(r["fund_id"])
            # (19) federal/trust activity separation
            if not calc.activity_permitted(fund["fund_type"], "ACQUISITION"):
                fail(
                    "ERR_FUND_ACTIVITY_NOT_PERMITTED",
                    "A FEDERAL fund may not support ACQUISITION activity",
                )
            # (20) the conservative COMMITTED figure gates
            if calc.committed_available(fund) < r["estimated_cost_cents"]:
                fail("ERR_INSUFFICIENT_FUND_AVAILABLE", "Committed availability is insufficient")
    r["status"] = outcome_raw
    r["decided_by_user_id"] = uid
    db.touch(r)
    return success(serializers.collection_review(r))


@bp.post("/campus/collection-reviews/<rid>/execute")
def execute_review(rid):
    _uid, role = auth()
    require_role(role, ["Registrar"])
    r = get_or_404("collection_reviews", rid, "CollectionReview")
    b = util.body()
    if r["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED review can be executed")
    if r["review_kind"] == "ACQUISITION":
        fund = db.STORE["funds"].get(r["fund_id"])
        # (6) the fund must still be ACTIVE
        if fund is None or fund["status"] != "ACTIVE":
            fail("ERR_FUND_FROZEN", "The fund is FROZEN")
        # (9) request shape for the optional payload field
        actual_raw = b.get("actual_cost_cents")
        if actual_raw is not None and (not util.is_int(actual_raw) or actual_raw < 1):
            fail("ERR_INVALID_REQUEST", "actual_cost_cents must be an integer >= 1")
        actual = actual_raw if actual_raw is not None else r["estimated_cost_cents"]
        # (19) activity permission
        if not calc.activity_permitted(fund["fund_type"], "ACQUISITION"):
            fail(
                "ERR_FUND_ACTIVITY_NOT_PERMITTED",
                "A FEDERAL fund may not support ACQUISITION activity",
            )
        # (20) the COMMITTED figure must cover the actual cost
        if calc.committed_available(fund) < actual:
            fail("ERR_INSUFFICIENT_FUND_AVAILABLE", "Committed availability is insufficient")
        # Create the acquired object (accession number is server-minted: the
        # PRD specifies title/declared value/status for the created object but
        # no accession number source) and post the acquisition expenditure.
        obj = db.new_entity(
            {
                "accession_number": "ACQ-" + db.new_id().replace("-", "")[:12].upper(),
                "title": r["proposed_object_title"],
                "declared_value_cents": actual,
                "is_cultural_property": False,
                "status": "IN_COLLECTION",
            }
        )
        db.STORE["collection_objects"][obj["id"]] = obj
        exp = db.new_entity(
            {
                "fund_id": fund["id"],
                "review_id": r["id"],
                "amount_cents": actual,
                "activity_type": "ACQUISITION",
                "memo": None,
                "status": "POSTED",
            }
        )
        db.STORE["expenditures"][exp["id"]] = exp
    else:
        obj = db.STORE["collection_objects"].get(r["object_id"])
        # (18) re-check at execute time: no ACTIVE loan on the object
        for l in db.STORE["loan_agreements"].values():
            if l["object_id"] == r["object_id"] and l["status"] == "ACTIVE":
                fail("ERR_OBJECT_ON_ACTIVE_LOAN", "The object is out on an active loan")
        if obj is not None:
            obj["status"] = (
                "REPATRIATED" if r["disposal_method"] == "REPATRIATION" else "DEACCESSIONED"
            )
            db.touch(obj)
        # Deepest cascade: object disposal cancels every non-terminal
        # (PROPOSED/COUNTERED/AGREED) loan of the object, and each cancelled
        # loan cancels its non-terminal (SUBMITTED/DISPUTED) condition reports.
        for l in db.STORE["loan_agreements"].values():
            if l["object_id"] == r["object_id"] and l["status"] in (
                "PROPOSED",
                "COUNTERED",
                "AGREED",
            ):
                l["status"] = "CANCELLED"
                db.touch(l)
                for rep in db.STORE["condition_reports"].values():
                    if rep["loan_id"] == l["id"] and rep["status"] in ("SUBMITTED", "DISPUTED"):
                        rep["status"] = "CANCELLED"
                        db.touch(rep)
    r["status"] = "EXECUTED"
    db.touch(r)
    return success(serializers.collection_review(r))
