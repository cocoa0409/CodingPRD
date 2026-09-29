"""ProgressiveEstimate endpoints (PRD 3.1)."""
from decimal import Decimal

from flask import Blueprint

import lookups
import response as resp
import serializers
import validation as v
from db import db, new_record, sorted_rows, touch
from errors import ApiError
from money import RATIO_ZERO, q4
from middleware import (
    CONSTRUCTION_MANAGER,
    INDEPENDENT_AUDITOR,
    OWNER_REPRESENTATIVE,
    PROGRAM_ADMIN,
    endpoint,
)

bp = Blueprint("estimates", __name__)

MILESTONE_RANK = {
    "SD": 1,
    "DD": 2,
    "CD_50": 3,
    "CD_100": 4,
    "GMP_BASIS": 5,
}
MILESTONE_CODES = tuple(MILESTONE_RANK.keys())
ESTIMATE_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "RECONCILED", "SUPERSEDED")
VARIANCE_BASES = ("NO_BASIS", "DECLARED_PRIOR", "HIGHEST_RECONCILED_MILESTONE")
SUPERSEDABLE = ("DRAFT", "SUBMITTED", "RETURNED")
VARIANCE_THRESHOLD_PCT = Decimal("0.0500")
READ_ROLES = (
    CONSTRUCTION_MANAGER,
    OWNER_REPRESENTATIVE,
    INDEPENDENT_AUDITOR,
    PROGRAM_ADMIN,
)


def compute_variance(project_id, milestone_rank, amount, prior_estimate_id,
                     exclude_id=None):
    """Ordered basis selection from PRD 3.1."""
    if prior_estimate_id is not None:
        basis = db.estimates.get(prior_estimate_id)
        if basis is None:
            return "NO_BASIS", None, RATIO_ZERO
        basis_kind = "DECLARED_PRIOR"
    else:
        candidates = [
            e for e in db.estimates.values()
            if e["project_id"] == project_id
            and e["id"] != exclude_id
            and e["status"] == "RECONCILED"
            and e["milestone_rank"] < milestone_rank
        ]
        if not candidates:
            return "NO_BASIS", None, RATIO_ZERO
        candidates.sort(
            key=lambda e: (e["milestone_rank"], e["created_at"], e["_seq"])
        )
        basis = candidates[-1]
        basis_kind = "HIGHEST_RECONCILED_MILESTONE"
    basis_amount = basis["submitted_cost_of_work"]
    variance_pct = q4((amount - basis_amount) / basis_amount)
    return basis_kind, basis["id"], variance_pct


@bp.route("/estimates", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def create_estimate():
    body = v.json_body()
    project_id = v.get_id(body, "project_id", required=True)
    milestone_code = v.get_enum(body, "milestone_code", MILESTONE_CODES, required=True)
    submitted_cost_of_work = v.get_money(
        body, "submitted_cost_of_work", required=True, positive=True
    )
    expected_project_version = v.get_int(
        body, "expected_project_version", required=True
    )
    prior_estimate_id = v.get_id(body, "prior_estimate_id", required=False)
    justification_note = v.get_str(
        body, "justification_note", required=False, min_len=0
    )

    project = lookups.project(project_id)
    prior = None
    if prior_estimate_id is not None:
        prior = lookups.estimate(prior_estimate_id)

    if project["version"] != expected_project_version:
        raise ApiError(
            "ERR_STALE_PROJECT_VERSION",
            "expected_project_version %s does not match %s"
            % (expected_project_version, project["version"]),
        )

    milestone_rank = MILESTONE_RANK[milestone_code]

    if prior is not None:
        if prior["project_id"] != project["id"]:
            raise ApiError(
                "ERR_CROSS_PROJECT_REFERENCE",
                "prior_estimate_id belongs to a different project",
            )
        if prior["milestone_rank"] >= milestone_rank:
            raise ApiError(
                "ERR_MILESTONE_RANK_REGRESSION",
                "prior_estimate_id must sit at a strictly lower milestone_rank",
            )

    basis_kind, basis_id, variance_pct = compute_variance(
        project["id"], milestone_rank, submitted_cost_of_work, prior_estimate_id
    )

    estimate = new_record({
        "project_id": project["id"],
        "prior_estimate_id": prior_estimate_id,
        "milestone_code": milestone_code,
        "milestone_rank": milestone_rank,
        "submitted_cost_of_work": submitted_cost_of_work,
        "variance_pct": variance_pct,
        "variance_basis": basis_kind,
        "variance_basis_estimate_id": basis_id,
        "justification_note": justification_note,
        "status": "DRAFT",
        "reconciliation_stale": False,
        "reconciliation_note": None,
        "superseded_by_estimate_id": None,
    })
    db.estimates[estimate["id"]] = estimate

    for other in list(db.estimates.values()):
        if other["id"] == estimate["id"]:
            continue
        if other["project_id"] != project["id"]:
            continue
        if other["milestone_code"] != milestone_code:
            continue
        if other["status"] not in SUPERSEDABLE:
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_estimate_id"] = estimate["id"]
        touch(other)

    touch(project)
    return resp.created(serializers.estimate(estimate))


@bp.route("/estimates/<eid>/submit", methods=["POST"])
@endpoint(CONSTRUCTION_MANAGER)
def submit_estimate(eid):
    body = v.json_body()
    justification_note = v.get_str(
        body, "justification_note", required=False, min_len=0
    )
    estimate = lookups.estimate(eid)
    if estimate["status"] not in ("DRAFT", "RETURNED"):
        raise ApiError(
            "ERR_ESTIMATE_STATE_INVALID",
            "estimate status is %s; submit requires DRAFT or RETURNED"
            % estimate["status"],
        )

    basis_kind, basis_id, variance_pct = compute_variance(
        estimate["project_id"],
        estimate["milestone_rank"],
        estimate["submitted_cost_of_work"],
        estimate["prior_estimate_id"],
        exclude_id=estimate["id"],
    )
    note = justification_note if justification_note is not None \
        else estimate["justification_note"]
    if variance_pct > VARIANCE_THRESHOLD_PCT:
        if note is None or str(note).strip() == "":
            raise ApiError(
                "ERR_VARIANCE_JUSTIFICATION_REQUIRED",
                "variance_pct %s exceeds 0.0500 and requires a justification_note"
                % variance_pct,
            )

    estimate["variance_basis"] = basis_kind
    estimate["variance_basis_estimate_id"] = basis_id
    estimate["variance_pct"] = variance_pct
    estimate["justification_note"] = note
    estimate["status"] = "SUBMITTED"
    touch(estimate)
    return resp.ok(serializers.estimate(estimate))


@bp.route("/estimates/<eid>/reconcile", methods=["POST"])
@endpoint(OWNER_REPRESENTATIVE)
def reconcile_estimate(eid):
    body = v.json_body()
    decision = v.get_enum(body, "decision", ("ACCEPT", "RETURN"), required=True)
    reconciliation_note = v.get_str(
        body, "reconciliation_note", required=False, min_len=0
    )
    estimate = lookups.estimate(eid)
    if estimate["status"] != "SUBMITTED":
        raise ApiError(
            "ERR_ESTIMATE_STATE_INVALID",
            "estimate status is %s; reconcile requires SUBMITTED" % estimate["status"],
        )
    if reconciliation_note is not None:
        estimate["reconciliation_note"] = reconciliation_note
    if decision == "ACCEPT":
        estimate["status"] = "RECONCILED"
        estimate["reconciliation_stale"] = False
    else:
        estimate["status"] = "RETURNED"
    touch(estimate)
    return resp.ok(serializers.estimate(estimate))


@bp.route("/estimates", methods=["GET"])
@endpoint(*READ_ROLES)
def list_estimates():
    limit, offset = v.pagination()
    project_id = v.query_filter("project_id")
    prior_estimate_id = v.query_filter("prior_estimate_id")
    basis_id = v.query_filter("variance_basis_estimate_id")
    superseded_by = v.query_filter("superseded_by_estimate_id")
    status = v.query_filter("status", ESTIMATE_STATUSES)
    milestone_code = v.query_filter("milestone_code", MILESTONE_CODES)
    if milestone_code is None:
        milestone_code = v.query_filter("milestone", MILESTONE_CODES)
    rows = []
    for row in db.estimates.values():
        if project_id is not None and row["project_id"] != project_id:
            continue
        if prior_estimate_id is not None and row["prior_estimate_id"] != prior_estimate_id:
            continue
        if basis_id is not None and row["variance_basis_estimate_id"] != basis_id:
            continue
        if superseded_by is not None and row["superseded_by_estimate_id"] != superseded_by:
            continue
        if status is not None and row["status"] != status:
            continue
        if milestone_code is not None and row["milestone_code"] != milestone_code:
            continue
        rows.append(row)
    rows = sorted_rows(rows)
    page, total = v.paginate(rows, limit, offset)
    return resp.listing([serializers.estimate(r) for r in page], limit, offset, total)


@bp.route("/estimates/<eid>", methods=["GET"])
@endpoint(*READ_ROLES)
def read_estimate(eid):
    return resp.ok(serializers.estimate(lookups.estimate(eid)))
