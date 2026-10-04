"""Pathogen sampling and establishment categorization (PRD §3.6)."""
from flask import Blueprint, request

import calc
import store
from authz import require_ownership, require_roles
from cascades import cat3_transition_cascade
from envelope import get_body, pagination_params, sort_and_page, success_list, success_object
from errors import (
    raise_err,
    ERR_INSPECTOR_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_PATHOGEN_SAMPLE_NOT_FOUND,
)
from guards import entity_or_404, establishment_or_404, require_granted, require_not_withdrawn
from store import insert, stamp_new, touch
from validate import PATHOGENS, not_future, require_enum, require_string, require_timestamp

bp = Blueprint("pathogen_samples", __name__)

READ_ROLES = ("EstablishmentManager", "Inspector", "SupervisoryReviewer", "DistrictManager", "ProgramAdministrator")


def _sample_or_404(sample_id):
    return entity_or_404("pathogen_samples", sample_id, ERR_PATHOGEN_SAMPLE_NOT_FOUND)


@bp.post("/inspection/pathogen-samples")
def create_sample():
    user_id, _ = require_roles("Inspector")
    body = get_body()
    establishment_id = require_string(body, "establishment_id")
    collected_by_inspector_id = require_string(body, "collected_by_inspector_id")
    pathogen = require_enum(body, "pathogen", PATHOGENS)
    collected_at = require_timestamp(body, "collected_at")

    require_ownership(user_id, collected_by_inspector_id)
    establishment = establishment_or_404(establishment_id)
    entity_or_404("inspectors", collected_by_inspector_id, ERR_INSPECTOR_NOT_FOUND)
    require_not_withdrawn(establishment)
    # Tier 7 (temporal) precedes the tier 9 grant gate (PRD §2.7).
    not_future(collected_at, "collected_at")
    require_granted(establishment)

    sample = {
        "establishment_id": establishment_id,
        "collected_by_inspector_id": collected_by_inspector_id,
        "pathogen": pathogen,
        "collected_at": collected_at,
        "result": "PENDING",
        "resulted_at": None,
    }
    stamp_new(sample)
    insert("pathogen_samples", sample)
    return success_object(sample, status=201)


@bp.get("/inspection/pathogen-samples")
def list_samples():
    require_roles(*READ_ROLES)
    rows = store.all_of("pathogen_samples")
    for param in ("establishment_id", "collected_by_inspector_id", "pathogen", "result"):
        value = request.args.get(param)
        if value is not None:
            rows = [s for s in rows if s.get(param) == value]
    limit, offset = pagination_params()
    page, total = sort_and_page(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/inspection/pathogen-samples/<sample_id>")
def get_sample(sample_id):
    require_roles(*READ_ROLES)
    return success_object(_sample_or_404(sample_id))


@bp.post("/inspection/pathogen-samples/<sample_id>/record-result")
def record_result(sample_id):
    require_roles("Inspector")
    sample = _sample_or_404(sample_id)
    establishment = establishment_or_404(sample["establishment_id"])
    require_not_withdrawn(establishment)
    if sample["result"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "record-result requires result PENDING")
    body = get_body()
    result = require_enum(body, "result", ("POSITIVE", "NEGATIVE"))

    # Per-pathogen categories BEFORE this result lands (the sample is still
    # PENDING, hence excluded from the windowed counts).
    before_map = calc.pathogen_category_map(establishment["id"])

    sample["result"] = result
    sample["resulted_at"] = store.clock_now()
    touch(sample)

    after_map = calc.pathogen_category_map(establishment["id"])
    new_category = calc.worst_category(after_map)
    # If no pathogen has sufficient samples the category is unchanged;
    # otherwise it is recomputed to the worst across sufficient pathogens. A
    # change is a cascade mutation of the establishment (version bump).
    if new_category is not None and new_category != establishment.get("pathogen_category"):
        establishment["pathogen_category"] = new_category
        touch(establishment)

    # Enforcement event: any pathogen transitioning INTO CAT_3 from a
    # different value auto-creates an IN_EFFECT notice (PRD §3.6).
    for pathogen in ("SALMONELLA", "CAMPYLOBACTER"):
        if before_map.get(pathogen) != "CAT_3" and after_map.get(pathogen) == "CAT_3":
            cat3_transition_cascade(establishment)
            break

    return success_object(sample)
