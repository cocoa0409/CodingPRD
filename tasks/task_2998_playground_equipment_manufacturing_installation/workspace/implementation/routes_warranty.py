"""Warranty claims and their two frozen coverage variants (PRD section 3.9)."""

from flask import Blueprint

import calc
import validate as v
from auth import authenticate
from envelope import list_response, object_response
from errors import ApiError
from store import parse_date, public, public_list, store

bp = Blueprint("warranty", __name__)

CLAIM_READ_ROLES = [
    "ManufacturerAdmin",
    "ComplianceOfficer",
    "DesignConsultant",
    "ClientRepresentative",
]
FILE_ROLES = ["ClientRepresentative", "ComplianceOfficer"]
DECISIONS = ("APPROVED", "DENIED")


@bp.route("/playground/warranty-claims", methods=["POST"])
def file_claim():
    authenticate(FILE_ROLES)
    body = v.raw_body()
    resolved = v.resolve_fks(body, [
        ("project_id", "project", True),
        ("placement_id", "placement", True),
    ])
    v.string(body, "project_id", min_len=1)
    v.string(body, "placement_id", min_len=1)
    quantity = v.integer(body, "quantity", minimum=1)
    failure_date = v.date_field(body, "failure_date")
    project = resolved["project_id"]
    placement = resolved["placement_id"]

    owner = store.placement_project(placement)
    if owner is None or owner["id"] != project["id"]:
        raise ApiError("ERR_WARRANTY_PLACEMENT_MISMATCH")

    if not project["installed_on"]:
        raise ApiError("ERR_PROJECT_NOT_INSTALLED")

    installed_on = parse_date(project["installed_on"])
    if failure_date < installed_on or failure_date > store.clock.today():
        raise ApiError("ERR_INVALID_FAILURE_DATE")

    model = store.require("model", placement["component_model_id"])
    coverage = calc.warranty_coverage(
        model, model["category"], quantity, project["installed_on"], failure_date)

    row = store.insert("claim", {
        "project_id": project["id"],
        "placement_id": placement["id"],
        "component_model_id": model["id"],
        "claim_category": model["category"],
        "quantity": quantity,
        "failure_date": failure_date.isoformat(),
        "elapsed_years": coverage["elapsed_years"],
        "coverage_variant": coverage["coverage_variant"],
        "covered_pct": coverage["covered_pct"],
        "reimbursement_cents": coverage["reimbursement_cents"],
        "status": "SUBMITTED",
    })
    return object_response(public(row), 201)


@bp.route("/playground/warranty-claims", methods=["GET"])
def list_claims():
    authenticate(CLAIM_READ_ROLES)
    limit, offset = v.pagination()
    rows = v.apply_filters(store.all("claim"), {
        "project_id": "project_id",
        "placement_id": "placement_id",
        "component_model_id": "component_model_id",
        "status": "status",
    })
    page, total = v.paginate(rows, limit, offset)
    return list_response(public_list(page), limit, offset, total)


@bp.route("/playground/warranty-claims/<claim_id>", methods=["GET"])
def get_claim(claim_id):
    authenticate(CLAIM_READ_ROLES)
    return object_response(public(store.require("claim", claim_id)))


@bp.route("/playground/warranty-claims/<claim_id>/decide", methods=["POST"])
def decide_claim(claim_id):
    authenticate(["ComplianceOfficer"])
    claim = store.require("claim", claim_id)
    body = v.raw_body()
    decision = v.enum(body, "decision", DECISIONS)

    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_CLAIM_INVALID_STATE")

    # Denial stays available at any coverage level; only approval is fiscal.
    if decision == "APPROVED" and claim["covered_pct"] == 0:
        raise ApiError("ERR_WARRANTY_EXPIRED")

    claim["status"] = decision
    store.touch(claim)
    return object_response(public(claim))
