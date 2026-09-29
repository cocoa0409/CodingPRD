"""Capital projects, funding applications and cost-recovery claims
(PRD section 3.9).
"""

from decimal import Decimal

from flask import Blueprint

import constants as C
import db
from db import store, touch, now
from errors import ApiError, invalid
from middleware import authenticate
from numeric import cents, divide
from response import created_response, object_response
from routes.common import (
    apply_scalar_filters,
    detail,
    filter_fk,
    page,
    pagination,
    resolve,
)
from services import finance
from shape import Body

bp = Blueprint("finance", __name__)


# ------------------------------------------------------------ capital projects
@bp.route("/capital-projects", methods=["GET"])
def list_projects():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("projects")
    rows = filter_fk(rows, "entry_point_id", "entry_points")
    rows = filter_fk(rows, "treatment_evaluation_id", "evaluations")
    rows = apply_scalar_filters(rows, ["funding_status", "construction_status"])
    return page(rows, limit, offset)


@bp.route("/capital-projects/<row_id>", methods=["GET"])
def get_project(row_id):
    authenticate(C.ANY_ROLE)
    return detail("projects", row_id)


@bp.route("/capital-projects/<row_id>", methods=["PATCH"])
def patch_project(row_id):
    authenticate(("FinanceOfficer",))
    project = resolve("projects", row_id)
    body = Body(["capital_cost_cents", "annual_om_cost_cents", "rate_design"])
    capital_cost = body.integer("capital_cost_cents", required=False, default=None, minimum=0)
    annual_om = body.integer("annual_om_cost_cents", required=False, default=None, minimum=0)
    rate_design = body.enum("rate_design", C.RATE_DESIGNS, required=False, default=None)

    if project["construction_status"] == "IN_SERVICE":
        raise ApiError("ERR_PROJECT_IN_SERVICE")

    if capital_cost is not None:
        project["capital_cost_cents"] = capital_cost
    if annual_om is not None:
        project["annual_om_cost_cents"] = annual_om
    if rate_design is not None:
        project["rate_design"] = rate_design
    finance.recompute_project(project)
    touch(project)
    return object_response(db.public(project))


@bp.route("/capital-projects/<row_id>/construction-status", methods=["POST"])
def advance_construction(row_id):
    authenticate(("FinanceOfficer",))
    project = resolve("projects", row_id)
    body = Body(["target_status", "concentrate_permit_ref"])
    target = body.enum("target_status", C.CONSTRUCTION_SEQUENCE)
    permit_ref = body.string("concentrate_permit_ref", required=False, default=None)

    current = project["construction_status"]
    index = C.CONSTRUCTION_SEQUENCE.index(current)
    successor = (
        C.CONSTRUCTION_SEQUENCE[index + 1]
        if index + 1 < len(C.CONSTRUCTION_SEQUENCE)
        else None
    )
    if target != successor:
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    if target == "BIDDING":
        if project["concentrate_permit_required"] and (
            permit_ref is None or permit_ref.strip() == ""
        ):
            raise ApiError("ERR_CONCENTRATE_PERMIT_REQUIRED")
        if project["funding_status"] != "AWARDED":
            raise ApiError("ERR_FUNDING_NOT_SECURED")

    project["construction_status"] = target
    touch(project)
    if target == "IN_SERVICE":
        entry_point = store.entry_points.get(project["entry_point_id"])
        if entry_point is not None:
            entry_point["treatment_status"] = "INSTALLED"
            touch(entry_point)
    return object_response(db.public(project))


@bp.route("/capital-projects/<row_id>/funding-applications", methods=["POST"])
def create_application(row_id):
    authenticate(("FinanceOfficer",))
    project = resolve("projects", row_id)
    body = Body(
        [
            "program",
            "amount_requested_cents",
            "disadvantaged_community",
            "expected_capital_project_version",
        ]
    )
    program = body.enum("program", C.FUNDING_PROGRAMS)
    amount = body.integer("amount_requested_cents", exclusive_minimum=0)
    disadvantaged = body.boolean("disadvantaged_community", required=False, default=False)
    expected_version = body.integer("expected_capital_project_version")

    if project["version"] != expected_version:
        raise ApiError("ERR_STALE_CAPITAL_PROJECT_VERSION")

    row = db.insert(
        "applications",
        {
            "capital_project_id": project["id"],
            "program": program,
            "amount_requested_cents": amount,
            "disadvantaged_community": disadvantaged,
            "forgiveness_pct": finance.forgiveness_pct_for(program, disadvantaged),
            "awarded_cents": None,
            "forgiven_cents": None,
            "status": "SUBMITTED",
            "decided_by_user_id": None,
            "decision_note": None,
            "withdraw_reason": None,
        },
    )
    project["funding_status"] = finance.derive_funding_status(project)
    touch(project)
    return created_response(db.public(row))


# -------------------------------------------------------- funding applications
@bp.route("/funding-applications", methods=["GET"])
def list_applications():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("applications")
    rows = filter_fk(rows, "capital_project_id", "projects")
    rows = apply_scalar_filters(rows, ["program", "status"])
    return page(rows, limit, offset)


@bp.route("/funding-applications/<row_id>", methods=["GET"])
def get_application(row_id):
    authenticate(C.ANY_ROLE)
    return detail("applications", row_id)


@bp.route("/funding-applications/<row_id>/decision", methods=["POST"])
def decide_application(row_id):
    user_id, _role = authenticate(("StateRegulator",))
    application = resolve("applications", row_id)
    body = Body(["action", "awarded_cents", "decision_note"])
    action = body.enum("action", ("AWARD", "DENY"))
    awarded = body.integer("awarded_cents", required=False, default=None, minimum=0)
    decision_note = body.string("decision_note", required=False, default=None)
    if action == "AWARD" and awarded is None:
        raise invalid("awarded_cents is required when awarding an application")
    if action == "DENY" and (decision_note is None or decision_note.strip() == ""):
        raise invalid("decision_note is required when denying an application")

    if application["status"] != "SUBMITTED":
        raise ApiError("ERR_APPLICATION_STATE_INVALID")

    project = store.projects.get(application["capital_project_id"])

    if action == "DENY":
        application["status"] = "DENIED"
        application["decided_by_user_id"] = user_id
        application["decision_note"] = decision_note
        touch(application)
        if project is not None:
            project["funding_status"] = finance.derive_funding_status(project)
            touch(project)
        return object_response(db.public(application))

    if awarded > application["amount_requested_cents"]:
        raise ApiError("ERR_AWARD_EXCEEDS_REQUEST")
    if project is not None:
        if project["funding_awarded_cents"] + awarded > project["capital_cost_cents"]:
            raise ApiError("ERR_AWARD_EXCEEDS_PROJECT_COST")

    application["status"] = "AWARDED"
    application["awarded_cents"] = awarded
    application["forgiven_cents"] = cents(
        divide(Decimal(awarded) * application["forgiveness_pct"], 100)
    )
    application["decided_by_user_id"] = user_id
    application["decision_note"] = decision_note
    touch(application)
    if project is not None:
        finance.recompute_project(project)
        touch(project)
    return object_response(db.public(application))


@bp.route("/funding-applications/<row_id>/withdraw", methods=["POST"])
def withdraw_application(row_id):
    authenticate(("FinanceOfficer",))
    application = resolve("applications", row_id)
    body = Body(["withdraw_reason"])
    reason = body.string("withdraw_reason", nonblank=True)

    if application["status"] not in ("SUBMITTED", "AWARDED"):
        raise ApiError("ERR_APPLICATION_STATE_INVALID")
    project = store.projects.get(application["capital_project_id"])
    if project is not None and project["construction_status"] != "PLANNED":
        raise ApiError("ERR_PROJECT_STATE_INVALID")

    application["status"] = "WITHDRAWN"
    application["withdraw_reason"] = reason
    application["awarded_cents"] = None
    application["forgiven_cents"] = None
    touch(application)
    if project is not None:
        finance.recompute_project(project)
        touch(project)
    return object_response(db.public(application))


# ------------------------------------------------------- cost-recovery claims
@bp.route("/cost-recovery-claims", methods=["POST"])
def create_claim():
    authenticate(("ComplianceOfficer",))
    body = Body(
        [
            "entry_point_id",
            "capital_project_id",
            "responsible_party_name",
            "investigation_basis",
            "allocation_pct",
            "investigation_cost_cents",
        ]
    )
    entry_point_id = body.string("entry_point_id")
    project_id = body.string("capital_project_id")
    party = body.string("responsible_party_name", min_len=1, max_len=120)
    basis = body.enum("investigation_basis", C.INVESTIGATION_BASES)
    allocation_pct = body.decimal("allocation_pct", minimum=1, maximum=100)
    investigation_cost = body.integer("investigation_cost_cents", minimum=0)

    resolve("entry_points", entry_point_id)
    project = resolve("projects", project_id)
    if project["entry_point_id"] != entry_point_id:
        raise ApiError("ERR_ENTRY_POINT_MISMATCH")

    basis_cents = cents(
        divide(
            (Decimal(project["capital_cost_cents"]) + Decimal(investigation_cost))
            * allocation_pct,
            100,
        )
    )
    row = db.insert(
        "claims",
        {
            "entry_point_id": entry_point_id,
            "capital_project_id": project_id,
            "responsible_party_name": party,
            "investigation_basis": basis,
            "allocation_pct": allocation_pct,
            "investigation_cost_cents": investigation_cost,
            "claim_basis_cents": basis_cents,
            "claimed_cents": None,
            "recovered_cents": None,
            "alloc_investigation_cents": None,
            "alloc_capital_cents": None,
            "alloc_om_reserve_cents": None,
            "alloc_rate_stabilization_cents": None,
            "status": "INVESTIGATING",
            "filed_at": None,
            "settled_at": None,
            "resolution_note": None,
        },
    )
    return created_response(db.public(row))


@bp.route("/cost-recovery-claims", methods=["GET"])
def list_claims():
    authenticate(C.ANY_ROLE)
    limit, offset = pagination()
    rows = db.sorted_rows("claims")
    rows = filter_fk(rows, "entry_point_id", "entry_points")
    rows = filter_fk(rows, "capital_project_id", "projects")
    rows = apply_scalar_filters(rows, ["status"])
    return page(rows, limit, offset)


@bp.route("/cost-recovery-claims/<row_id>", methods=["GET"])
def get_claim(row_id):
    authenticate(C.ANY_ROLE)
    return detail("claims", row_id)


@bp.route("/cost-recovery-claims/<row_id>/file", methods=["POST"])
def file_claim(row_id):
    authenticate(("ComplianceOfficer",))
    claim = resolve("claims", row_id)
    body = Body(["claimed_cents"])
    claimed = body.integer("claimed_cents", exclusive_minimum=0)
    if claim["status"] != "INVESTIGATING":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    claim["claimed_cents"] = claimed
    claim["status"] = "CLAIM_FILED"
    claim["filed_at"] = now()
    touch(claim)
    return object_response(db.public(claim))


@bp.route("/cost-recovery-claims/<row_id>/resolve", methods=["POST"])
def resolve_claim(row_id):
    authenticate(("FinanceOfficer",))
    claim = resolve("claims", row_id)
    body = Body(["action", "recovered_cents", "resolution_note"])
    action = body.enum("action", ("SETTLE", "DISMISS"))
    recovered = body.integer("recovered_cents", required=False, default=None, minimum=0)
    resolution_note = body.string("resolution_note", required=False, default=None)
    if action == "SETTLE" and recovered is None:
        raise invalid("recovered_cents is required when settling a claim")
    if action == "DISMISS" and (resolution_note is None or resolution_note.strip() == ""):
        raise invalid("resolution_note is required when dismissing a claim")

    if action == "DISMISS":
        if claim["status"] not in ("INVESTIGATING", "CLAIM_FILED"):
            raise ApiError("ERR_CLAIM_STATE_INVALID")
        claim["status"] = "DISMISSED"
        claim["recovered_cents"] = 0
        claim["alloc_investigation_cents"] = 0
        claim["alloc_capital_cents"] = 0
        claim["alloc_om_reserve_cents"] = 0
        claim["alloc_rate_stabilization_cents"] = 0
        claim["resolution_note"] = resolution_note
        touch(claim)
        return object_response(db.public(claim))

    if claim["status"] != "CLAIM_FILED":
        raise ApiError("ERR_CLAIM_STATE_INVALID")
    if recovered > (claim["claimed_cents"] or 0):
        raise ApiError("ERR_RECOVERY_EXCEEDS_CLAIM")

    project = store.projects.get(claim["capital_project_id"])
    if project is None:
        raise ApiError("ERR_PROJECT_NOT_FOUND")

    alloc_investigation, alloc_capital, alloc_reserve, alloc_stabilization = (
        finance.allocate_recovery(claim, project, recovered)
    )
    claim["status"] = "SETTLED"
    claim["recovered_cents"] = recovered
    claim["alloc_investigation_cents"] = alloc_investigation
    claim["alloc_capital_cents"] = alloc_capital
    claim["alloc_om_reserve_cents"] = alloc_reserve
    claim["alloc_rate_stabilization_cents"] = alloc_stabilization
    claim["resolution_note"] = resolution_note
    claim["settled_at"] = now()
    touch(claim)

    project["recovered_cents"] = project["recovered_cents"] + alloc_capital
    finance.recompute_project(project)
    touch(project)
    return object_response(db.public(claim))
