"""Appeals and supervisory review (PRD §3.9)."""
from flask import Blueprint, request

import store
from authz import require_ownership, require_roles
from cascades import maybe_auto_suspend_for_escalation
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_APPEAL_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_NONCOMPLIANCE_RECORD_NOT_FOUND,
    ERR_SOD_REVIEWER_IS_ISSUER,
)
from guards import entity_or_404, establishment_or_404, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import require_enum, require_string

bp = Blueprint("appeals", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


@bp.post("/inspection/appeals")
def create_appeal():
    user_id, _ = require_roles("EstablishmentManager")
    body = get_body()
    nr_id = require_string(body, "noncompliance_record_id")
    grounds = require_string(body, "grounds", min_len=10)

    nr = entity_or_404("noncompliance_records", nr_id, ERR_NONCOMPLIANCE_RECORD_NOT_FOUND)
    require_ownership(user_id, nr["establishment_id"])
    require_not_withdrawn(establishment_or_404(nr["establishment_id"]))
    if nr["status"] not in ("OPEN", "RESPONSE_SUBMITTED", "ESCALATED"):
        raise_err(ERR_INVALID_STATE, "appeal requires the record to be OPEN, RESPONSE_SUBMITTED or ESCALATED")

    appeal = {
        "noncompliance_record_id": nr["id"],
        "grounds": grounds,
        "status": "FILED",
        "decided_by_reviewer_id": None,
        "decided_at": None,
    }
    stamp_new(appeal)
    insert("appeals", appeal)
    # Same request: the record moves to APPEALED, remembering its filing status.
    nr["status_before_appeal"] = nr["status"]
    nr["status"] = "APPEALED"
    touch(nr)
    return success_object(appeal, status=201)


@bp.get("/inspection/noncompliance-records/<nr_id>/appeals")
def list_appeals(nr_id):
    require_roles(*READ_ROLES)
    entity_or_404("noncompliance_records", nr_id, ERR_NONCOMPLIANCE_RECORD_NOT_FOUND)
    rows = [a for a in store.all_of("appeals") if a["noncompliance_record_id"] == nr_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [a for a in rows if a["status"] == status_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/appeals/<appeal_id>/decide")
def decide_appeal(appeal_id):
    user_id, _ = require_roles("SupervisoryReviewer")
    appeal = entity_or_404("appeals", appeal_id, ERR_APPEAL_NOT_FOUND)
    nr = entity_or_404("noncompliance_records", appeal["noncompliance_record_id"], ERR_NONCOMPLIANCE_RECORD_NOT_FOUND)
    require_not_withdrawn(establishment_or_404(nr["establishment_id"]))
    # Tier 5 (state) precedes tier 10 (segregation of duties) per PRD §2.7.
    if appeal["status"] != "FILED" or nr["status"] != "APPEALED":
        raise_err(ERR_INVALID_STATE, "decide requires a FILED appeal on an APPEALED record")
    if user_id == nr["issued_by_inspector_id"]:
        raise_err(ERR_SOD_REVIEWER_IS_ISSUER, "reviewer must not be the issuing inspector")
    body = get_body()
    outcome = require_enum(body, "outcome", ("AFFIRM", "REMAND", "VACATE"))

    appeal["decided_by_reviewer_id"] = user_id
    appeal["decided_at"] = store.clock_now()
    if outcome == "AFFIRM":
        appeal["status"] = "AFFIRMED"
        nr["status"] = "ESCALATED"
        touch(appeal)
        touch(nr)
        # The escalation count is re-evaluated at affirm time (PRD §3.9).
        maybe_auto_suspend_for_escalation(nr)
    elif outcome == "REMAND":
        appeal["status"] = "REMANDED"
        nr["status"] = "OPEN"
        touch(appeal)
        touch(nr)
    else:  # VACATE
        appeal["status"] = "VACATED"
        nr["status"] = "VACATED"
        touch(appeal)
        touch(nr)
    return success_object(appeal)
