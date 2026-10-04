"""Warranty claims: intake, evidence, inspection requests, adjudication, reopen."""
from decimal import Decimal
from flask import Blueprint

from db import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_REGISTRATION_NOT_ACTIVE,
    ERR_PHOTO_EVIDENCE_INSUFFICIENT, ERR_INSPECTION_INCOMPLETE,
    ERR_STALE_CLAIM_VERSION, not_found,
)
from middleware import require_roles
from response import success, list_response
from services.helpers import (
    body_json, require_fields, require_string, require_enum, require_nonneg_int,
    stamp_common, touch, now_ts, parse_clock,
)
from services.calculations import (
    SCHEDULE_FN, TIER_SCHEDULE, TIER_RULES, DETERMINATION_SHARE, WORKMANSHIP_DELTA,
    DECERT_THRESHOLD, liability_factor, round_half_up_cents,
)

bp = Blueprint("claims", __name__)

EVIDENCE_TYPES = ("PHOTO", "CORE_SAMPLE", "DOCUMENT")
DETERMINATIONS = ("MANUFACTURER_DEFECT", "INSTALLATION_ERROR", "MIXED", "NO_DEFECT")


def _get_claim(cid):
    claim = db.claims.get(cid)
    if claim is None:
        raise not_found("WarrantyClaim")
    return claim


@bp.post("/program/warranty-claims")
def create_claim():
    require_roles("Claimant")
    data = body_json()
    require_fields(data, ["registration_id", "description", "claim_labor_cost_cents"])
    registration_id = require_string(data, "registration_id")
    description = data["description"]
    if not isinstance(description, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "description must be a string")
    labor = require_nonneg_int(data, "claim_labor_cost_cents")
    with db.lock:
        reg = db.registrations.get(registration_id)
        if reg is None:
            raise not_found("WarrantyRegistration")
        if reg["status"] != "ACTIVE":
            raise ApiError(ERR_REGISTRATION_NOT_ACTIVE, 409, "Registration is not ACTIVE")
        cert = db.certifications.get(reg["certification_id"])
        contractor = db.contractors.get(cert["contractor_id"]) if cert else None
        snapshot = contractor["workmanship_score"] if contractor else 100
        claim = stamp_common({
            "registration_id": registration_id,
            "description": description,
            "claim_labor_cost_cents": labor,
            "evidence": [],
            "photo_count": 0,
            "determination": None,
            "filed_at": db.clock,
            "filing_workmanship_score": snapshot,
            "status": "SUBMITTED",
        })
        db.claims[claim["id"]] = claim
    return success(claim, status=201)


@bp.get("/program/warranty-claims/<cid>")
def get_claim(cid):
    require_roles("ProgramAdmin", "Contractor", "Claimant")
    with db.lock:
        claim = _get_claim(cid)
    return success(claim)


@bp.post("/program/warranty-claims/<cid>/evidence")
def add_evidence(cid):
    require_roles("Claimant", "ProgramAdmin")
    data = body_json()
    require_fields(data, ["evidence_type", "note"])
    evidence_type = require_enum(data, "evidence_type", EVIDENCE_TYPES)
    note = data["note"]
    if not isinstance(note, str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "note must be a string")
    with db.lock:
        claim = _get_claim(cid)
        if claim["status"] in ("RESOLVED", "DENIED"):
            raise ApiError(ERR_INVALID_STATE, 409, "Claim is terminal")
        claim["evidence"].append({
            "evidence_type": evidence_type,
            "note": note,
            "submitted_at": now_ts(),
        })
        claim["photo_count"] = sum(
            1 for e in claim["evidence"] if e["evidence_type"] == "PHOTO"
        )
        if claim["status"] == "SUBMITTED" and claim["photo_count"] >= 2:
            claim["status"] = "EVIDENCE_REVIEW"
        touch(claim)
    return success(claim, status=201)


@bp.post("/program/warranty-claims/<cid>/request-inspection")
def request_inspection(cid):
    require_roles("ProgramAdmin")
    with db.lock:
        claim = _get_claim(cid)
        if claim["status"] not in ("EVIDENCE_REVIEW", "INSPECTION_REQUESTED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim is not in EVIDENCE_REVIEW or INSPECTION_REQUESTED")
        order = stamp_common({
            "claim_id": claim["id"],
            "inspector_id": None,
            "service_date": None,
            "findings": None,
            "confirms_defect": None,
            "status": "REQUESTED",
        })
        db.inspection_orders[order["id"]] = order
        if claim["status"] == "EVIDENCE_REVIEW":
            claim["status"] = "INSPECTION_REQUESTED"
        touch(claim)
    return success(order, status=201)


@bp.get("/program/warranty-claims/<cid>/inspection-orders")
def list_claim_inspection_orders(cid):
    require_roles("ProgramAdmin", "Contractor")
    with db.lock:
        claim = _get_claim(cid)
        rows = sorted(
            (o for o in db.inspection_orders.values() if o["claim_id"] == claim["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)


def _compute_remedy(claim, reg, determination):
    """Pinned evaluation order per PRD 3.6. Returns remedy dict fields."""
    activated = parse_clock(reg["activated_at"])
    filed = parse_clock(claim["filed_at"])
    completed_years = (filed - activated).days // 365
    if completed_years < 0:
        completed_years = 0
    if reg["coverage_class"] == "MIXED_MANUFACTURER":
        schedule = "STANDARD"
    else:
        schedule = TIER_SCHEDULE[reg["coverage_tier"]]
    pct = SCHEDULE_FN[schedule](completed_years)
    lines = [c for c in db.components.values() if c["registration_id"] == reg["id"]]
    material_total = sum(line["material_cost_cents"] for line in lines)
    pool = sum(
        round_half_up_cents(Decimal(line["material_cost_cents"]) * pct / 100)
        for line in lines
    )
    share = DETERMINATION_SHARE[determination]
    material_covered = round_half_up_cents(share * pool)
    homeowner_share = round_half_up_cents(share * (material_total - pool))
    # labor
    if reg["coverage_class"] == "MIXED_MANUFACTURER":
        labor_covered = 0
    else:
        rules = TIER_RULES[reg["coverage_tier"]]
        if completed_years >= rules["labor_years"]:
            labor_covered = 0
        else:
            base = min(claim["claim_labor_cost_cents"], rules["labor_cap_cents"])
            labor_covered = round_half_up_cents(share * base)
    factor = liability_factor(claim["filing_workmanship_score"])
    liability = round_half_up_cents(
        (Decimal(1) - share) * (material_total + claim["claim_labor_cost_cents"]) * factor
    )
    delta = WORKMANSHIP_DELTA[determination]
    return {
        "determination": determination,
        "completed_years": completed_years,
        "schedule_used": schedule,
        "material_pct": pct,
        "prorated_material_pool_cents": pool,
        "material_covered_cents": material_covered,
        "homeowner_material_share_cents": homeowner_share,
        "labor_covered_cents": labor_covered,
        "contractor_liability_cents": liability,
        "workmanship_delta_applied": delta,
    }


@bp.post("/program/warranty-claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["determination", "expected_claim_version"])
    determination = require_enum(data, "determination", DETERMINATIONS)
    ecv = data["expected_claim_version"]
    if not isinstance(ecv, int) or isinstance(ecv, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400, "expected_claim_version must be an integer")
    with db.lock:
        claim = _get_claim(cid)
        if claim["photo_count"] < 2:
            raise ApiError(ERR_PHOTO_EVIDENCE_INSUFFICIENT, 422,
                           "photo_count below 2")
        outstanding = any(
            o["claim_id"] == claim["id"] and o["status"] in ("REQUESTED", "SCHEDULED")
            for o in db.inspection_orders.values()
        )
        if outstanding:
            raise ApiError(ERR_INSPECTION_INCOMPLETE, 422,
                           "Linked inspection order outstanding")
        if claim["status"] not in ("EVIDENCE_REVIEW", "INSPECTION_COMPLETED"):
            raise ApiError(ERR_INVALID_STATE, 409,
                           "Claim is not adjudicable from its current state")
        if ecv != claim["version"]:
            raise ApiError(ERR_STALE_CLAIM_VERSION, 412, "Stale claim version")
        if determination == "NO_DEFECT":
            claim["determination"] = determination
            claim["status"] = "DENIED"
            touch(claim)
            return success(claim)
        # resolution path — a claim carries at most one remedy allocation;
        # re-adjudication after a reopen supersedes the reversed allocation
        for rid, existing in list(db.remedies.items()):
            if existing["claim_id"] == claim["id"]:
                del db.remedies[rid]
        reg = db.registrations.get(claim["registration_id"])
        cert = db.certifications.get(reg["certification_id"])
        contractor = db.contractors.get(cert["contractor_id"])
        fields = _compute_remedy(claim, reg, determination)
        remedy = stamp_common({
            "claim_id": claim["id"],
            "status": "ACTIVE",
            **fields,
        })
        db.remedies[remedy["id"]] = remedy
        claim["determination"] = determination
        claim["status"] = "RESOLVED"
        # standing mutation after remedy persisted
        contractor["outstanding_liability_cents"] += remedy["contractor_liability_cents"]
        contractor["workmanship_score"] = max(
            0, contractor["workmanship_score"] + remedy["workmanship_delta_applied"]
        )
        touch(contractor)
        if determination in ("INSTALLATION_ERROR", "MIXED") and \
                contractor["workmanship_score"] <= DECERT_THRESHOLD:
            for c in db.certifications.values():
                if c["contractor_id"] == contractor["id"] and c["status"] == "ACTIVE":
                    c["status"] = "SUSPENDED"
                    touch(c)
        touch(claim)
    return success(claim)


@bp.post("/program/warranty-claims/<cid>/reopen")
def reopen_claim(cid):
    require_roles("ProgramAdmin")
    data = body_json()
    require_fields(data, ["reason"])
    if not isinstance(data["reason"], str):
        raise ApiError(ERR_INVALID_REQUEST, 400, "reason must be a string")
    with db.lock:
        claim = _get_claim(cid)
        if claim["status"] != "RESOLVED":
            raise ApiError(ERR_INVALID_STATE, 409, "Claim is not RESOLVED")
        remedy = next(
            (r for r in db.remedies.values()
             if r["claim_id"] == claim["id"] and r["status"] == "ACTIVE"),
            None,
        )
        if remedy is None:
            raise ApiError(ERR_INVALID_STATE, 409, "No ACTIVE remedy allocation")
        reg = db.registrations.get(claim["registration_id"])
        cert = db.certifications.get(reg["certification_id"])
        contractor = db.contractors.get(cert["contractor_id"])
        remedy["status"] = "REVERSED"
        touch(remedy)
        contractor["outstanding_liability_cents"] -= remedy["contractor_liability_cents"]
        contractor["workmanship_score"] = min(
            100, contractor["workmanship_score"] - remedy["workmanship_delta_applied"]
        )
        touch(contractor)
        claim["status"] = "EVIDENCE_REVIEW"
        touch(claim)
    return success(claim)


@bp.get("/program/warranty-claims/<cid>/remedy-allocation")
def list_remedy_allocation(cid):
    require_roles("ProgramAdmin", "Contractor", "Claimant")
    with db.lock:
        claim = _get_claim(cid)
        rows = sorted(
            (r for r in db.remedies.values() if r["claim_id"] == claim["id"]),
            key=lambda x: x["created_at"],
        )
    return list_response(rows, len(rows), len(rows), 0)
