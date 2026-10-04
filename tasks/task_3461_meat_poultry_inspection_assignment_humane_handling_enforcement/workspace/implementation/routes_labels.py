"""Label claim review and documentation minimums (PRD §3.7)."""
from flask import Blueprint, request

import calc
import store
from authz import require_ownership, require_roles
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_INSUFFICIENT_DOCUMENTATION,
    ERR_INVALID_STATE,
    ERR_LABEL_APPLICATION_NOT_FOUND,
)
from guards import (
    establishment_or_404,
    entity_or_404,
    require_granted,
    require_not_suspended,
    require_not_withdrawn,
)
from store import insert, stamp_new, touch
from validate import LABEL_CLAIMS, require_enum, require_string, require_string_array

bp = Blueprint("label_applications", __name__)

LIST_ROLES = ("EstablishmentManager", "LabelOfficer", "DistrictManager", "ProgramAdministrator")


def _label_or_404(label_id):
    return entity_or_404("label_applications", label_id, ERR_LABEL_APPLICATION_NOT_FOUND)


@bp.post("/inspection/label-applications")
def create_label():
    user_id, _ = require_roles("EstablishmentManager")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    product_name = require_string(body, "product_name")
    label_claim = require_enum(body, "label_claim", LABEL_CLAIMS)
    documentation_refs = require_string_array(body, "documentation_refs")

    require_ownership(user_id, establishment_id)
    establishment = establishment_or_404(establishment_id)
    require_not_withdrawn(establishment)

    label = {
        "establishment_id": establishment_id,
        "product_name": product_name,
        "label_claim": label_claim,
        "documentation_refs": list(documentation_refs),
        "status": "SUBMITTED",
        "revision_count": 0,
    }
    stamp_new(label)
    insert("label_applications", label)
    return success_object(label, status=201)


@bp.get("/inspection/establishments/<est_id>/label-applications")
def list_labels(est_id):
    require_roles(*LIST_ROLES)
    establishment_or_404(est_id)
    rows = [l for l in store.all_of("label_applications") if l["establishment_id"] == est_id]
    status_filter = request.args.get("status")
    if status_filter is not None:
        rows = [l for l in rows if l["status"] == status_filter]
    claim_filter = request.args.get("label_claim")
    if claim_filter is not None:
        rows = [l for l in rows if l["label_claim"] == claim_filter]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.post("/inspection/label-applications/<label_id>/begin-review")
def begin_review(label_id):
    require_roles("LabelOfficer")
    label = _label_or_404(label_id)
    require_not_withdrawn(establishment_or_404(label["establishment_id"]))
    if label["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "begin-review requires status SUBMITTED")
    label["status"] = "UNDER_REVIEW"
    touch(label)
    return success_object(label)


@bp.post("/inspection/label-applications/<label_id>/decide")
def decide(label_id):
    require_roles("LabelOfficer")
    label = _label_or_404(label_id)
    establishment = establishment_or_404(label["establishment_id"])
    require_not_withdrawn(establishment)
    if label["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, "decide requires status UNDER_REVIEW")
    body = get_body()
    decision = require_enum(body, "decision", ("APPROVE", "REJECT", "RETURN"))

    if decision == "APPROVE":
        # Approval gates beyond state, in pipeline order (PRD §3.7): grant,
        # then suspension, then the documentation minimum.
        require_granted(establishment)
        require_not_suspended(establishment)
        minimum = calc.LABEL_DOCUMENTATION_MINIMUM[label["label_claim"]]
        if len(label["documentation_refs"]) < minimum:
            raise_err(ERR_INSUFFICIENT_DOCUMENTATION, "documentation_refs below the claim minimum")
        label["status"] = "APPROVED"
    elif decision == "REJECT":
        label["status"] = "REJECTED"
    else:
        label["status"] = "RETURNED"
    touch(label)
    return success_object(label)


@bp.post("/inspection/label-applications/<label_id>/resubmit")
def resubmit(label_id):
    user_id, _ = require_roles("EstablishmentManager")
    label = _label_or_404(label_id)
    require_ownership(user_id, label["establishment_id"])
    establishment = establishment_or_404(label["establishment_id"])
    require_not_withdrawn(establishment)
    if label["status"] != "RETURNED":
        raise_err(ERR_INVALID_STATE, "resubmit requires status RETURNED")
    require_not_suspended(establishment)
    body = get_body()
    documentation_refs = require_string_array(body, "documentation_refs")

    label["documentation_refs"] = list(documentation_refs)
    label["status"] = "SUBMITTED"
    label["revision_count"] += 1
    touch(label)
    return success_object(label)
