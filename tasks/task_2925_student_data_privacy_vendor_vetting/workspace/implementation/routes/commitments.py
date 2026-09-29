"""Data-element commitments: minimization, retention and the exposure chain (PRD 3.4)."""
from flask import Blueprint

from core import auth, envelope, logic, serialize, store, validate
from core.errors import ApiError
from core.validate import F

bp = Blueprint("commitments", __name__)


@bp.post("/data-element-commitments")
def create_commitment():
    auth.actor("VendorLiaison", "PrivacyAnalyst")
    data = validate.body([
        F("review_id", "str"),
        F("element_code", "enum", members=set(logic.ELEMENT_CODES)),
        F("justified_purpose", "str", lo=1, hi=500),
        F("retention_days", "int", lo=1, hi=1825),
        F("deletion_method", "enum", members=set(logic.DELETION_METHODS)),
        F("expected_review_version", "int"),
    ])
    review = auth.need("review", data["review_id"])

    if review["status"] not in logic.NON_TERMINAL_REVIEW_STATUSES:
        raise ApiError("ERR_REVIEW_STATE_INVALID")
    # Rung 21: the optimistic-concurrency token sits above every business rule.
    if data["expected_review_version"] != review["version"]:
        raise ApiError("ERR_STALE_REVIEW_VERSION")

    tier = logic.element_sensitivity_tier(data["element_code"])
    if data["retention_days"] > logic.TIER_RETENTION_CAP[tier]:
        raise ApiError("ERR_RETENTION_EXCEEDS_STATUTORY_CAP")

    application = store.applications[review["application_id"]]
    row = store.new_row({
        "review_id": review["id"],
        "element_code": data["element_code"],
        "sensitivity_tier": tier,
        "justified_purpose": data["justified_purpose"],
        "retention_days": data["retention_days"],
        "deletion_method": data["deletion_method"],
        "status": "PROPOSED",
        "superseded_by_commitment_id": None,
        "decided_by_analyst_id": None,
    })
    row["is_minimized"] = logic.commitment_is_minimized(row, application)
    row["element_points"] = logic.commitment_element_points(
        tier, row["retention_days"], row["deletion_method"])

    # Re-authoring an element supersedes the earlier proposal (PRD 3.4).
    for earlier in logic.review_commitments(review["id"]):
        if earlier["element_code"] == row["element_code"] and earlier["status"] == "PROPOSED":
            earlier["status"] = "SUPERSEDED"
            earlier["superseded_by_commitment_id"] = row["id"]
            store.bump(earlier)

    store.commitments[row["id"]] = row
    store.bump(review)
    return envelope.created(serialize.commitment(row))


@bp.get("/data-element-commitments")
def list_commitments():
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    filters = envelope.query_filters({
        "review_id": None,
        "superseded_by_commitment_id": None,
        "decided_by_analyst_id": None,
        "status": set(logic.COMMITMENT_STATUSES),
        "element_code": set(logic.ELEMENT_CODES),
    })
    rows = list(store.commitments.values())
    for key in ("review_id", "superseded_by_commitment_id", "decided_by_analyst_id", "status",
                "element_code"):
        if key in filters:
            rows = [r for r in rows if r[key] == filters[key]]
    return envelope.paged(store.ordered(rows), serialize.commitment)


@bp.get("/data-element-commitments/<commitment_id>")
def read_commitment(commitment_id):
    auth.actor("PrivacyOfficeAdmin", "PrivacyAnalyst", "VendorLiaison")
    return envelope.ok(serialize.commitment(auth.need("commitment", commitment_id)))


@bp.post("/data-element-commitments/<commitment_id>/decide")
def decide_commitment(commitment_id):
    user_id, _role = auth.actor("PrivacyAnalyst")
    data = validate.body([F("disposition", "enum", members={"ACCEPT", "REJECT"})])
    row = auth.need("commitment", commitment_id)
    review = store.reviews[row["review_id"]]

    # Rung 7: the assignee organizes the commitments, another analyst decides them.
    auth.sod_or_403(user_id != review["assigned_analyst_id"])

    if review["status"] in logic.TERMINAL_REVIEW_STATUSES:
        raise ApiError("ERR_REVIEW_STATE_INVALID")
    if row["status"] not in ("PROPOSED", "ACCEPTED"):
        raise ApiError("ERR_COMMITMENT_ALREADY_DECIDED")

    application = store.applications[review["application_id"]]
    vendor = store.vendors[review["vendor_id"]]
    if vendor["privacy_posture"] == "FROZEN":
        raise ApiError("ERR_VENDOR_POSTURE_FROZEN")

    disposition = data["disposition"]
    if disposition == "ACCEPT":
        if row["sensitivity_tier"] > application["max_permitted_tier"]:
            raise ApiError("ERR_ELEMENT_TIER_NOT_PERMITTED")
        if row["status"] != "PROPOSED":
            raise ApiError("ERR_DISPOSITION_NOT_APPLICABLE")

    row["status"] = "ACCEPTED" if disposition == "ACCEPT" else "REJECTED"
    row["decided_by_analyst_id"] = user_id
    row["is_minimized"] = logic.commitment_is_minimized(row, application)
    store.bump(row)

    # Full re-evaluation, never a delta: exposure, then risk, then posture.
    logic.recompute_application_exposure(application, force=True)
    logic.recompute_vendor(vendor)
    return envelope.ok(serialize.commitment(row))
