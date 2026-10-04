"""PCFReport endpoints (PRD 3.6): create-with-supersede (OCC on the
collection), submission computing both footprint variants, the third-party
verification pipeline with segregation of duties, and publication firing
cascade A (supersede -> retire -> revoke)."""
from flask import Blueprint, request

from auth import authenticate, authorize
from calcs import pcf_footprint, pcf_input_set, periods_overlap
from constants import ALL_ROLES, BOUNDARIES, VERIFICATION_ACTIONS
from envelope import list_endpoint, success
from errors import ApiError
from serialize import serialize_report
from store import STORE, new_common, touch
from util import get_body, is_int, parse_dt, req_dt, req_enum, req_int, req_str

bp = Blueprint("reports", __name__)

IN_VERIFICATION_PIPELINE = ("SUBMITTED", "IN_VERIFICATION", "VERIFIED")


@bp.route("/carpetloop/pcf-reports", methods=["POST"])
def create_report():
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    body = get_body()
    # Priority 4: collection FK.
    collection = None
    if body.get("collection_id") is not None:
        collection = STORE.collections.get(body["collection_id"])
        if collection is None:
            raise ApiError("ERR_COLLECTION_NOT_FOUND", 404, "Collection does not exist")
    # Priority 6: report creation requires an ACTIVE collection.
    if collection is not None and collection["status"] != "ACTIVE":
        raise ApiError("ERR_COLLECTION_SUNSET", 409, "Collection is SUNSET")
    # Priority 7: OCC — expected_collection_version equals the current version.
    ecv = body.get("expected_collection_version")
    if is_int(ecv) and collection is not None and ecv != collection["version"]:
        raise ApiError(
            "ERR_STALE_VERSION",
            412,
            "expected_collection_version does not match the collection's version",
        )
    # Priority 10: the half-open period must not overlap a same-collection
    # report still inside the verification pipeline; touching endpoints do not
    # overlap. Overlapping DRAFTs are superseded below; overlapping PUBLISHED
    # reports are superseded at publish time — neither blocks creation.
    ps = parse_dt(body.get("period_start"))
    pe = parse_dt(body.get("period_end"))
    if ps is not None and pe is not None and collection is not None:
        for r in STORE.reports.values():
            if (
                r["collection_id"] == collection["id"]
                and r["status"] in IN_VERIFICATION_PIPELINE
                and periods_overlap(ps, pe, r["period_start"], r["period_end"])
            ):
                raise ApiError(
                    "ERR_REPORT_PERIOD_OVERLAP",
                    409,
                    "Period overlaps a report in the verification pipeline",
                )
    # Priority 11: request shape. period_end must be strictly later than
    # period_start (PRD 2.5); expected_collection_version is non-optional.
    req_str(body, "collection_id")
    ps = req_dt(body, "period_start")
    pe = req_dt(body, "period_end")
    boundary = req_enum(body, "boundary", BOUNDARIES)
    if not is_int(ecv):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            400,
            "expected_collection_version is required and must be an integer",
        )
    if not (pe > ps):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "period_end must be strictly later than period_start"
        )
    # Supersede overlapping same-collection DRAFT reports as part of the create.
    for r in list(STORE.reports.values()):
        if (
            r["collection_id"] == collection["id"]
            and r["status"] == "DRAFT"
            and periods_overlap(ps, pe, r["period_start"], r["period_end"])
        ):
            r["status"] = "SUPERSEDED"
            touch(STORE, r)
    # The create advances the collection's version.
    touch(STORE, collection)
    r = new_common(STORE)
    r.update(
        {
            "collection_id": collection["id"],
            "period_start": ps,
            "period_end": pe,
            "boundary": boundary,
            "operational_kgco2e_per_m2": None,
            "lifecycle_kgco2e_per_m2": None,
            "submitted_by": None,
            "verifier_org": None,
            "verified_by": None,
            "status": "DRAFT",
        }
    )
    STORE.reports[r["id"]] = r
    return success(serialize_report(r), 201)


@bp.route("/carpetloop/pcf-reports/<report_id>", methods=["GET"])
def get_report(report_id):
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    r = STORE.reports.get(report_id)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    return success(serialize_report(r), 200)


@bp.route("/carpetloop/pcf-reports", methods=["GET"])
def list_reports():
    _uid, role = authenticate()
    authorize(role, ALL_ROLES)
    filters = {}
    for f in ("collection_id", "status"):
        v = request.args.get(f)
        if v is not None:
            filters[f] = v
    return list_endpoint(STORE.reports.values(), request.args, filters, serialize_report)


@bp.route("/carpetloop/pcf-reports/<report_id>/submit", methods=["POST"])
def submit_report(report_id):
    uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    r = STORE.reports.get(report_id)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    # Priority 5: DRAFT -> SUBMITTED only.
    if r["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not in DRAFT")
    # Priority 6: the collection must still be ACTIVE.
    collection = STORE.collections.get(r["collection_id"])
    if collection is not None and collection["status"] != "ACTIVE":
        raise ApiError("ERR_COLLECTION_SUNSET", 409, "Collection is SUNSET")
    # Priority 11: a non-empty input set is required.
    if not pcf_input_set(STORE, r):
        raise ApiError(
            "ERR_EMPTY_REPORT_INPUT", 422, "The report's input set of batches is empty"
        )
    operational, lifecycle = pcf_footprint(STORE, r)
    r["operational_kgco2e_per_m2"] = operational
    r["lifecycle_kgco2e_per_m2"] = lifecycle
    r["submitted_by"] = uid
    r["status"] = "SUBMITTED"
    touch(STORE, r)
    return success(serialize_report(r), 200)


@bp.route("/carpetloop/pcf-reports/<report_id>/verification", methods=["POST"])
def verification_report(report_id):
    uid, role = authenticate()
    # Priority 2: endpoint-level roles, then the action-level split when the
    # action is parseable (ASSIGN -> SustainabilityManager; CLEAR|FAIL ->
    # Verifier). An unparseable action falls through to the priority-11 shape
    # check.
    authorize(role, {"SustainabilityManager", "Verifier"})
    body = get_body()
    action = body.get("action")
    if action == "ASSIGN":
        authorize(role, {"SustainabilityManager"})
    elif action in ("CLEAR", "FAIL"):
        authorize(role, {"Verifier"})
    # Priority 4.
    r = STORE.reports.get(report_id)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    # Priority 5: ASSIGN exists from SUBMITTED; CLEAR/FAIL from IN_VERIFICATION.
    if action == "ASSIGN":
        if r["status"] != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not in SUBMITTED")
    elif action in ("CLEAR", "FAIL"):
        if r["status"] != "IN_VERIFICATION":
            raise ApiError("ERR_INVALID_STATE", 409, "Report is not in IN_VERIFICATION")
    # Priority 8: segregation of duties — the verifier's X-User-ID must differ
    # from the report's submitted_by.
    if action in ("CLEAR", "FAIL") and uid == r["submitted_by"]:
        raise ApiError(
            "ERR_SEGREGATION_OF_DUTIES",
            403,
            "A verifier cannot clear or fail a report they submitted",
        )
    # Priority 11: action enum; ASSIGN requires verifier_org; FAIL requires
    # findings_count >= 1.
    action = req_enum(body, "action", VERIFICATION_ACTIONS)
    if action == "ASSIGN":
        verifier_org = req_str(body, "verifier_org")
        r["verifier_org"] = verifier_org
        r["status"] = "IN_VERIFICATION"
    elif action == "CLEAR":
        r["verified_by"] = uid
        r["status"] = "VERIFIED"
    else:  # FAIL
        req_int(body, "findings_count", min_inclusive=1)
        r["status"] = "REJECTED"
    touch(STORE, r)
    return success(serialize_report(r), 200)


@bp.route("/carpetloop/pcf-reports/<report_id>/revise", methods=["POST"])
def revise_report(report_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    r = STORE.reports.get(report_id)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    # Priority 5: REJECTED -> DRAFT only.
    if r["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not in REJECTED")
    r["submitted_by"] = None
    r["verifier_org"] = None
    r["verified_by"] = None
    r["operational_kgco2e_per_m2"] = None
    r["lifecycle_kgco2e_per_m2"] = None
    r["status"] = "DRAFT"
    touch(STORE, r)
    return success(serialize_report(r), 200)


@bp.route("/carpetloop/pcf-reports/<report_id>/publish", methods=["POST"])
def publish_report(report_id):
    _uid, role = authenticate()
    authorize(role, {"SustainabilityManager"})
    r = STORE.reports.get(report_id)
    if r is None:
        raise ApiError("ERR_REPORT_NOT_FOUND", 404, "Report does not exist")
    # Priority 5: VERIFIED -> PUBLISHED only.
    if r["status"] != "VERIFIED":
        raise ApiError("ERR_INVALID_STATE", 409, "Report is not in VERIFIED")
    r["status"] = "PUBLISHED"
    touch(STORE, r)
    # Cascade A (PRD 2.9), link 1: overlapping same-collection PUBLISHED
    # reports -> SUPERSEDED.
    superseded_report_ids = []
    for other in STORE.reports.values():
        if (
            other["id"] != r["id"]
            and other["collection_id"] == r["collection_id"]
            and other["status"] == "PUBLISHED"
            and periods_overlap(
                r["period_start"], r["period_end"], other["period_start"], other["period_end"]
            )
        ):
            other["status"] = "SUPERSEDED"
            touch(STORE, other)
            superseded_report_ids.append(other["id"])
    # Link 2: PUBLISHED claims resting on a superseded report -> RETIRED.
    retired_claim_ids = []
    if superseded_report_ids:
        for c in STORE.claims.values():
            if c["status"] == "PUBLISHED" and c["report_id"] in superseded_report_ids:
                c["status"] = "RETIRED"
                touch(STORE, c)
                retired_claim_ids.append(c["id"])
    # Link 3: ISSUED packages referencing a retired claim -> REVOKED.
    if retired_claim_ids:
        for p in STORE.packages.values():
            if p["status"] == "ISSUED" and p["claim_id"] in retired_claim_ids:
                p["status"] = "REVOKED"
                touch(STORE, p)
    return success(serialize_report(r), 200)
