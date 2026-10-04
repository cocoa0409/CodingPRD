"""Engagement and EvidenceArtifact endpoints."""
from __future__ import annotations

from flask import Blueprint, request

from db import db
from errors import (
    err_engagement_not_in_progress, err_engagement_not_yet_open,
    err_cip_evidence_required, err_evidence_not_reviewable, err_invalid_interval,
    err_invalid_request, err_invalid_state, err_not_found,
    err_standard_not_applicable,
)
from helpers import (
    clock_now, entity_has_standard, new_common, parse_dt, parse_pagination,
    serialize, sort_and_page, touch,
)
from middleware import require_roles
from response import success_list, success_object
from services import recompute_coverage_fraction

bp = Blueprint("engagements", __name__)

READ_ROLES = (
    "ComplianceAuditor", "RegionalEntityReviewer", "FederalReviewer",
    "EntityComplianceOfficer",
)

ENGAGEMENT_TYPES = {"AUDIT", "SPOT_CHECK", "SELF_CERTIFICATION"}
ARTIFACT_KINDS = {"OPERATING_RECORD", "ACCESS_LOG", "MAINTENANCE_RECORD"}


# ---------------------------------------------------------------------------
# Engagements
# ---------------------------------------------------------------------------

@bp.post("/engagements")
def create_engagement():
    require_roles("ComplianceAuditor")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")

    entity_id = body.get("entity_id")
    if not isinstance(entity_id, str):
        raise err_invalid_request("entity_id is required")
    entity = db.registered_entities.get(entity_id)
    if entity is None:
        raise err_not_found("RegisteredEntity not found")

    etype = body.get("engagement_type")
    if etype not in ENGAGEMENT_TYPES:
        raise err_invalid_request("engagement_type must be AUDIT, SPOT_CHECK, or SELF_CERTIFICATION")

    stds = body.get("standard_ids")
    if not isinstance(stds, list) or not stds or not all(isinstance(s, str) for s in stds):
        raise err_invalid_request("standard_ids must be a non-empty array of strings")

    period_start = parse_dt(body.get("period_start"), "period_start")
    period_end = parse_dt(body.get("period_end"), "period_end")
    if period_end <= period_start:
        raise err_invalid_interval("period_end must be strictly after period_start")

    for sid in stds:
        if not entity_has_standard(entity, sid):
            raise err_standard_not_applicable(f"standard {sid} not applicable to entity")

    row = new_common()
    row.update({
        "entity_id": entity_id,
        "engagement_type": etype,
        "standard_ids": list(stds),
        "period_start": period_start,
        "period_end": period_end,
        "status": "SCHEDULED",
        "coverage_fraction": 0.0,
    })
    db.engagements[row["id"]] = row
    return success_object(serialize(row), status=201)


@bp.get("/engagements")
def list_engagements():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.engagements.values())
    entity_id = request.args.get("entity_id")
    if entity_id is not None:
        rows = [r for r in rows if r["entity_id"] == entity_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/engagements/<engagementId>")
def get_engagement(engagementId):
    require_roles(*READ_ROLES)
    row = db.engagements.get(engagementId)
    if row is None:
        raise err_not_found("Engagement not found")
    return success_object(serialize(row))


@bp.post("/engagements/<engagementId>/start")
def start_engagement(engagementId):
    require_roles("ComplianceAuditor")
    row = db.engagements.get(engagementId)
    if row is None:
        raise err_not_found("Engagement not found")
    if row["status"] != "SCHEDULED":
        raise err_invalid_state("engagement is not SCHEDULED")
    # applicability re-checked at start
    entity = db.registered_entities.get(row["entity_id"])
    if entity is not None:
        for sid in row["standard_ids"]:
            if not entity_has_standard(entity, sid):
                raise err_standard_not_applicable(f"standard {sid} not applicable to entity")
    if clock_now() < row["period_start"]:
        raise err_engagement_not_yet_open()
    row["status"] = "IN_PROGRESS"
    touch(row)
    return success_object(serialize(row))


@bp.post("/engagements/<engagementId>/complete")
def complete_engagement(engagementId):
    require_roles("ComplianceAuditor")
    row = db.engagements.get(engagementId)
    if row is None:
        raise err_not_found("Engagement not found")
    if row["status"] != "IN_PROGRESS":
        raise err_invalid_state("engagement is not IN_PROGRESS")
    row["status"] = "COMPLETED"
    recompute_coverage_fraction(row)
    touch(row)
    return success_object(serialize(row))


@bp.post("/engagements/<engagementId>/cancel")
def cancel_engagement(engagementId):
    require_roles("ComplianceAuditor")
    row = db.engagements.get(engagementId)
    if row is None:
        raise err_not_found("Engagement not found")
    if row["status"] not in ("SCHEDULED", "IN_PROGRESS"):
        raise err_invalid_state("engagement cannot be cancelled from its current state")
    # cascade: SUBMITTED evidence -> REJECTED
    for art in db.evidence.values():
        if art["engagement_id"] == row["id"] and art["status"] == "SUBMITTED":
            art["status"] = "REJECTED"
            touch(art)
    row["status"] = "CANCELLED"
    recompute_coverage_fraction(row)
    touch(row)
    return success_object(serialize(row))


# ---------------------------------------------------------------------------
# Evidence
# ---------------------------------------------------------------------------

@bp.post("/evidence")
def create_evidence():
    require_roles("EntityComplianceOfficer")
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise err_invalid_request("request body must be a JSON object")

    engagement_id = body.get("engagement_id")
    if not isinstance(engagement_id, str):
        raise err_invalid_request("engagement_id is required")
    engagement = db.engagements.get(engagement_id)
    if engagement is None:
        raise err_not_found("Engagement not found")

    standard_id = body.get("standard_id")
    if not isinstance(standard_id, str):
        raise err_invalid_request("standard_id is required")
    kind = body.get("artifact_kind")
    if kind not in ARTIFACT_KINDS:
        raise err_invalid_request("artifact_kind must be OPERATING_RECORD, ACCESS_LOG, or MAINTENANCE_RECORD")

    coverage_start = parse_dt(body.get("coverage_start"), "coverage_start")
    coverage_end = parse_dt(body.get("coverage_end"), "coverage_end")
    cip_asset_id = body.get("cip_asset_id")

    # CIP access-log requirement runs before the engagement-in-progress check
    if kind == "ACCESS_LOG":
        if not cip_asset_id or not isinstance(cip_asset_id, str):
            raise err_cip_evidence_required()
        asset = db.cip_assets.get(cip_asset_id)
        if asset is None:
            raise err_not_found("CIPAsset not found")
        if asset["status"] != "ACTIVE" or not asset["is_bes_cyber_asset"]:
            raise err_cip_evidence_required()
    else:
        cip_asset_id = None

    # temporal checks
    if engagement["status"] != "IN_PROGRESS":
        raise err_engagement_not_in_progress()
    if coverage_end <= coverage_start:
        raise err_invalid_interval("coverage_end must be strictly after coverage_start")

    # standard must be in scope of the engagement
    if standard_id not in engagement["standard_ids"]:
        raise err_standard_not_applicable("standard_id not in engagement scope")

    row = new_common()
    row.update({
        "engagement_id": engagement_id,
        "standard_id": standard_id,
        "artifact_kind": kind,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "submitted_at": clock_now(),
        "status": "SUBMITTED",
        "review_note": "",
        "cip_asset_id": cip_asset_id,
    })
    db.evidence[row["id"]] = row
    recompute_coverage_fraction(engagement)
    touch(engagement)
    return success_object(serialize(row), status=201)


@bp.get("/evidence")
def list_evidence():
    require_roles(*READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.evidence.values())
    engagement_id = request.args.get("engagement_id")
    if engagement_id is not None:
        rows = [r for r in rows if r["engagement_id"] == engagement_id]
    cip_asset_id = request.args.get("cip_asset_id")
    if cip_asset_id is not None:
        rows = [r for r in rows if r.get("cip_asset_id") == cip_asset_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = sort_and_page(rows, limit, offset)
    return success_list([serialize(r) for r in page], limit, offset, total)


@bp.get("/evidence/<evidenceId>")
def get_evidence(evidenceId):
    require_roles(*READ_ROLES)
    row = db.evidence.get(evidenceId)
    if row is None:
        raise err_not_found("EvidenceArtifact not found")
    return success_object(serialize(row))


def _review_evidence(evidenceId, outcome):
    require_roles("ComplianceAuditor")
    row = db.evidence.get(evidenceId)
    if row is None:
        raise err_not_found("EvidenceArtifact not found")
    if row["status"] != "SUBMITTED":
        raise err_invalid_state("evidence is not SUBMITTED")
    engagement = db.engagements[row["engagement_id"]]
    if engagement["status"] != "IN_PROGRESS":
        raise err_evidence_not_reviewable()
    body = request.get_json(silent=True)
    if isinstance(body, dict):
        note = body.get("review_note")
        if note is not None:
            if not isinstance(note, str):
                raise err_invalid_request("review_note must be a string")
            row["review_note"] = note
    row["status"] = outcome
    touch(row)
    recompute_coverage_fraction(engagement)
    touch(engagement)
    return success_object(serialize(row))


@bp.post("/evidence/<evidenceId>/accept")
def accept_evidence(evidenceId):
    return _review_evidence(evidenceId, "ACCEPTED")


@bp.post("/evidence/<evidenceId>/reject")
def reject_evidence(evidenceId):
    return _review_evidence(evidenceId, "REJECTED")
