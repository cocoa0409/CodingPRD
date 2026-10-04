"""CarbonClaim and OffsetRetirement endpoints (PRD 3.7)."""
import uuid
from decimal import Decimal

from flask import Blueprint, request

from auth import authenticate, authorize
from calcs import claim_required_offset, coverage_of
from constants import ALL_ROLES, BOUNDARIES, CLAIM_TYPES, REGISTRIES, REVIEW_DECISIONS
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_claim, serialize_offset
from store import STORE, new_common, touch
from util import get_body, opt_str, req_decimal, req_enum, req_int, req_str

bp = Blueprint("claims", __name__)


@bp.route("/carpetloop/carbon-claims", methods=["POST"])
def create_claim():
    uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    body = get_body()
    # Priority 4, canonical order: collection, then report, then target.
    collection = None
    if body.get("collection_id") is not None:
        collection = STORE.collections.get(body["collection_id"])
        if collection is None:
            raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    report = None
    if body.get("report_id") is not None:
        report = STORE.reports.get(body["report_id"])
        if report is None:
            raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    target = None
    if body.get("manufacturing_target_id") is not None:
        target = STORE.targets.get(body["manufacturing_target_id"])
        if target is None:
            raise ApiError("ERR_TARGET_NOT_FOUND", 404, "Manufacturing target does not exist")
    # Priority 9, in the scaffold's listed order: boundary equals the report's
    # boundary; CARBON_NEGATIVE must declare CRADLE_TO_GRAVE; CARBON_NEGATIVE
    # must name a manufacturing_target_id. (Report PUBLISHED and target posture
    # are submission gates, not creation gates.)
    boundary_raw = body.get("boundary")
    if report is not None and isinstance(boundary_raw, str):
        if boundary_raw != report["boundary"]:
            raise ApiError(
                "ERR_BOUNDARY_MISMATCH",
                422,
                "The claim's boundary must equal the referenced report's boundary",
            )
    if body.get("claim_type") == "CARBON_NEGATIVE":
        if boundary_raw != "CRADLE_TO_GRAVE":
            raise ApiError(
                "ERR_NEGATIVE_REQUIRES_CRADLE_TO_GRAVE",
                422,
                "CARBON_NEGATIVE claims must declare CRADLE_TO_GRAVE",
            )
        if not body.get("manufacturing_target_id"):
            raise ApiError(
                "ERR_TARGET_REQUIRED_FOR_NEGATIVE",
                422,
                "CARBON_NEGATIVE claims must name a manufacturing_target_id",
            )
    # Priority 11: request shape.
    req_str(body, "collection_id")
    req_str(body, "report_id")
    claim_type = req_enum(body, "claim_type", CLAIM_TYPES)
    volume = req_decimal(body, "claimed_volume_m2", min_exclusive=0)
    boundary = req_enum(body, "boundary", BOUNDARIES)
    target_id = opt_str(body, "manufacturing_target_id")
    c = new_common(STORE)
    c.update(
        {
            "collection_id": collection["id"],
            "report_id": report["id"],
            "manufacturing_target_id": target_id,
            "claim_type": claim_type,
            "claimed_volume_m2": volume,
            "boundary": boundary,
            "required_offset_kgco2e": None,
            "retired_kgco2e": Decimal("0"),
            "offset_coverage": "NONE",
            "created_by": uid,
            "reviewed_by": None,
            "status": "DRAFT",
        }
    )
    STORE.claims[c["id"]] = c
    return success(serialize_claim(c), 201)


@bp.route("/carpetloop/carbon-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    return success(serialize_claim(c), 200)


@bp.route("/carpetloop/carbon-claims", methods=["GET"])
def list_claims():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("collection_id", "report_id", "manufacturing_target_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.claims.values(), request.args, filters, serialize_claim)


@bp.route("/carpetloop/carbon-claims/<claim_id>/submit", methods=["POST"])
def submit_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    # Priority 5: DRAFT -> IN_REVIEW, and REJECTED -> IN_REVIEW (resubmission).
    if c["status"] not in ("DRAFT", "REJECTED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Claim cannot be submitted from its state")
    # Priority 9: the referenced report must be PUBLISHED; a CARBON_NEGATIVE
    # claim's referenced target posture must not be BREACHED.
    report = STORE.reports.get(c["report_id"])
    if report is None or report["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REPORT_NOT_PUBLISHED", 422, "The referenced report is not PUBLISHED"
        )
    if c["claim_type"] == "CARBON_NEGATIVE":
        target = STORE.targets.get(c["manufacturing_target_id"])
        if target is not None and target["posture"] == "BREACHED":
            raise ApiError(
                "ERR_TARGET_BREACHED",
                422,
                "The referenced manufacturing target's posture is BREACHED",
            )
    c["required_offset_kgco2e"] = claim_required_offset(c, report)
    c["offset_coverage"] = coverage_of(c)
    if c["status"] == "REJECTED":
        # Resubmission: the earlier review cannot carry over.
        c["reviewed_by"] = None
    c["status"] = "IN_REVIEW"
    touch(STORE, c)
    return success(serialize_claim(c), 200)


@bp.route("/carpetloop/carbon-claims/<claim_id>/review", methods=["POST"])
def review_claim(claim_id):
    uid, role = authenticate()
    authorize(role, {"ClaimsApprover"})
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    # Priority 5: review exists from IN_REVIEW only.
    if c["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not in IN_REVIEW")
    # Priority 8: segregation of duties — the reviewer must differ from the
    # claim's creator.
    if uid == c["created_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "A reviewer cannot review a claim they created",
        )
    body = get_body()
    # Priority 11: decision enum.
    decision = req_enum(body, "decision", REVIEW_DECISIONS)
    c["status"] = "APPROVED" if decision == "APPROVE" else "REJECTED"
    c["reviewed_by"] = uid
    touch(STORE, c)
    return success(serialize_claim(c), 200)


@bp.route("/carpetloop/carbon-claims/<claim_id>/publish", methods=["POST"])
def publish_claim(claim_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    # Priority 5: APPROVED -> PUBLISHED only.
    if c["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim is not in APPROVED")
    # Priority 9: the report must still be PUBLISHED, then FULL coverage.
    report = STORE.reports.get(c["report_id"])
    if report is None or report["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REPORT_NOT_PUBLISHED", 422, "The referenced report is not PUBLISHED"
        )
    if c["offset_coverage"] != "FULL":
        raise ApiError(
            "ERR_OFFSET_COVERAGE_INSUFFICIENT",
            422,
            "Claim publication requires FULL offset coverage",
        )
    c["status"] = "PUBLISHED"
    touch(STORE, c)
    return success(serialize_claim(c), 200)


@bp.route("/carpetloop/carbon-claims/<claim_id>/offsets", methods=["POST"])
def create_offset(claim_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    # Priority 5: offsets retire against a claim IN_REVIEW or APPROVED.
    if c["status"] not in ("IN_REVIEW", "APPROVED"):
        raise ApiError(
            "ERR_INVALID_STATE", 409, "Offsets retire only against IN_REVIEW or APPROVED claims"
        )
    body = get_body()
    # Priority 11: registry enum, vintage_year >= 2020, positive quantity.
    registry = req_enum(body, "registry", REGISTRIES)
    vintage_year = req_int(body, "vintage_year", min_inclusive=2020)
    quantity = req_decimal(body, "quantity_kgco2e", min_exclusive=0)
    now = STORE.now()
    o = {
        "id": str(uuid.uuid4()),
        "created_at": now,
        "claim_id": c["id"],
        "registry": registry,
        "vintage_year": vintage_year,
        "quantity_kgco2e": quantity,
        "retired_at": now,
        "_seq": STORE.next_seq(),
    }
    STORE.offsets[o["id"]] = o
    # Retirement is immediate at creation; coverage is recomputed against the
    # standing requirement — retiring offsets never changes the requirement.
    c["retired_kgco2e"] += quantity
    c["offset_coverage"] = coverage_of(c)
    touch(STORE, c)
    return success(serialize_offset(o), 201)


@bp.route("/carpetloop/carbon-claims/<claim_id>/offsets", methods=["GET"])
def list_offsets(claim_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    c = STORE.claims.get(claim_id)
    if c is None:
        raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    items = [o for o in STORE.offsets.values() if o["claim_id"] == claim_id]
    return list_endpoint(items, request.args, {}, serialize_offset)
