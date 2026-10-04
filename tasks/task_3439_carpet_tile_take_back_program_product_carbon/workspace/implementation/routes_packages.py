"""SpecPackage endpoints (PRD 3.8): issuance is a create-with-supersede
operation (OCC on the collection) that continues a per-(architect_firm,
collection_id) issuance sequence."""
from flask import Blueprint, request

from auth import authenticate, authorize
from constants import ALL_ROLES
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_package
from store import STORE, new_common, touch
from util import get_body, is_int, opt_str, req_str

bp = Blueprint("packages", __name__)


@bp.route("/carpetloop/spec-packages", methods=["POST"])
def create_package():
    uid, role = authenticate()
    authorize(role, {"Specifier"})
    body = get_body()
    # Priority 4, canonical order: collection, then report, then claim.
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
    claim = None
    if body.get("claim_id") is not None:
        claim = STORE.claims.get(body["claim_id"])
        if claim is None:
            raise ApiError("ERR_CLAIM_NOT_FOUND", 404, "Claim does not exist")
    # Priority 7: OCC — expected_collection_version equals the current version.
    ecv = body.get("expected_collection_version")
    if is_int(ecv) and collection is not None and ecv != collection["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_collection_version does not match the collection's version",
        )
    # Priority 9: the report must be PUBLISHED; a referenced claim must be
    # PUBLISHED.
    if report is not None and report["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_REPORT_NOT_PUBLISHED", 422, "The referenced report is not PUBLISHED"
        )
    if claim is not None and claim["status"] != "PUBLISHED":
        raise ApiError(
            "ERR_CLAIM_NOT_PUBLISHED", 422, "The referenced claim is not PUBLISHED"
        )
    # Priority 11: request shape (expected_collection_version non-optional).
    architect_firm = req_str(body, "architect_firm")
    req_str(body, "collection_id")
    req_str(body, "report_id")
    claim_id = opt_str(body, "claim_id")
    if not is_int(ecv):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "expected_collection_version is required and must be an integer",
        )
    # Supersede the prior ISSUED package for the same firm+collection pair and
    # continue the pair's issuance sequence (starting at 1).
    pair = [
        p
        for p in STORE.packages.values()
        if p["architect_firm"] == architect_firm and p["collection_id"] == collection["id"]
    ]
    next_version = 1 + max((p["package_version"] for p in pair), default=0)
    for p in pair:
        if p["status"] == "ISSUED":
            p["status"] = "SUPERSEDED"
            touch(STORE, p)
    # The create advances the collection's version.
    touch(STORE, collection)
    p = new_common(STORE)
    p.update(
        {
            "architect_firm": architect_firm,
            "collection_id": collection["id"],
            "report_id": report["id"],
            "claim_id": claim_id,
            "package_version": next_version,
            "status": "ISSUED",
            "created_by": uid,
        }
    )
    STORE.packages[p["id"]] = p
    return success(serialize_package(p), 201)


@bp.route("/carpetloop/spec-packages/<package_id>", methods=["GET"])
def get_package(package_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    p = STORE.packages.get(package_id)
    if p is None:
        raise ApiError("ERR_PACKAGE_NOT_FOUND", 404, "Spec package does not exist")
    return success(serialize_package(p), 200)


@bp.route("/carpetloop/spec-packages", methods=["GET"])
def list_packages():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("architect_firm", "collection_id", "report_id", "claim_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.packages.values(), request.args, filters, serialize_package)
