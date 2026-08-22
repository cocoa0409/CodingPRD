"""The mix book: qualification, suspension, reinstatement, retirement (PRD 3.1)."""
from flask import Blueprint

import auth
import cascade
import constants
import db
import errors
import lookup
import response
import serialize
import validation

bp = Blueprint("mix", __name__)

_LIVE_RUN_STATES = ("SCHEDULED", "BLOCKED", "TENSIONED", "CURING",
                    "RELEASE_READY", "RELEASED")


@bp.post("/mix-designs")
def create_mix_design():
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    body = validation.get_body()
    code = validation.req_str(body, "code", min_len=1, max_len=32)
    strength_class = validation.req_enum(body, "strength_class",
                                         constants.STRENGTH_CLASSES)
    design_psi = validation.req_int(body, "design_28day_psi", exclusive_min=0)
    release_psi = validation.req_int(body, "required_release_psi", exclusive_min=0)
    if release_psi >= design_psi:
        errors.fail(errors.ERR_VALIDATION,
                    "required_release_psi must be strictly less than design_28day_psi.")
    w_c_ratio = validation.req_number(body, "w_c_ratio", exclusive_min=0, maximum=1)
    cement = validation.req_int(body, "cement_lb_per_cy", exclusive_min=0)
    unit_cost = validation.req_int(body, "unit_cost_cents_per_cy", exclusive_min=0)
    for existing in db.store.mix_designs.values():
        if existing["code"] == code:
            errors.fail(errors.ERR_DUPLICATE_MIX_CODE,
                        "code %s is already used by another mix design." % code)
    row = db.new_row(db.store.mix_designs, {
        "code": code,
        "strength_class": strength_class,
        "design_28day_psi": design_psi,
        "required_release_psi": release_psi,
        "w_c_ratio": w_c_ratio,
        "cement_lb_per_cy": cement,
        "unit_cost_cents_per_cy": unit_cost,
        "status": "DRAFT",
        "suspension_reason": None,
        "qualified_at": None,
    })
    db.mark_fresh(row)
    return response.object_response(serialize.mix_design(row), 201)


@bp.get("/mix-designs/<mix_id>")
def get_mix_design(mix_id):
    auth.require_any()
    row = lookup.mix_design(mix_id)
    return response.object_response(serialize.mix_design(row), 200)


@bp.post("/mix-designs/<mix_id>/qualify")
def qualify(mix_id):
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    mix = lookup.mix_design(mix_id)
    if mix["status"] != "DRAFT":
        errors.fail(errors.ERR_MIX_DESIGN_INVALID_STATE,
                    "Only a DRAFT mix design may be qualified.")
    mix["status"] = "QUALIFIED"
    mix["qualified_at"] = db.store.now_iso()
    db.touch(mix)
    return response.object_response(serialize.mix_design(mix), 200)


@bp.post("/mix-designs/<mix_id>/suspend")
def suspend(mix_id):
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    mix = lookup.mix_design(mix_id)
    body = validation.get_body()
    reason = validation.req_text(body, "reason")
    if mix["status"] != "QUALIFIED":
        errors.fail(errors.ERR_MIX_DESIGN_INVALID_STATE,
                    "Only a QUALIFIED mix design may be suspended.")
    mix["status"] = "SUSPENDED"
    mix["suspension_reason"] = reason
    db.touch(mix)

    # hop 1: SCHEDULED runs on this mix become BLOCKED
    for run in db.store.bed_runs.values():
        if run["mix_design_id"] != mix["id"] or run["status"] != "SCHEDULED":
            continue
        run["status"] = "BLOCKED"
        run["blocked_reason"] = "MIX_SUSPENDED"
        db.touch(run)
        # hop 2 (caused by hop 1): their PENDING pieces go on hold
        for piece in db.store.pieces.values():
            if piece["bed_run_id"] != run["id"] or piece["qc_status"] != "PENDING":
                continue
            piece["qc_status"] = "HOLD"
            piece["qc_hold_reason"] = "MIX_SUSPENDED"
            db.touch(piece)
            # hop 3 (caused by hop 2): the owning project recomputes counters
            cascade.touch_project_of(piece)
    return response.object_response(serialize.mix_design(mix), 200)


@bp.post("/mix-designs/<mix_id>/reinstate")
def reinstate(mix_id):
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    mix = lookup.mix_design(mix_id)
    if mix["status"] != "SUSPENDED":
        errors.fail(errors.ERR_MIX_DESIGN_INVALID_STATE,
                    "Only a SUSPENDED mix design may be reinstated.")
    mix["status"] = "QUALIFIED"
    mix["suspension_reason"] = None
    db.touch(mix)

    # compensation hop 1: BLOCKED runs return to SCHEDULED
    for run in db.store.bed_runs.values():
        if run["mix_design_id"] != mix["id"] or run["status"] != "BLOCKED":
            continue
        run["status"] = "SCHEDULED"
        run["blocked_reason"] = None
        db.touch(run)
        # compensation hop 2: pieces held for MIX_SUSPENDED return to PENDING
        for piece in db.store.pieces.values():
            if (piece["bed_run_id"] != run["id"]
                    or piece["qc_status"] != "HOLD"
                    or piece["qc_hold_reason"] != "MIX_SUSPENDED"):
                continue
            piece["qc_status"] = "PENDING"
            piece["qc_hold_reason"] = None
            db.touch(piece)
            # compensation hop 3: the owning project recomputes held_piece_count
            cascade.touch_project_of(piece)
    return response.object_response(serialize.mix_design(mix), 200)


@bp.post("/mix-designs/<mix_id>/retire")
def retire(mix_id):
    auth.require(constants.ROLE_QUALITY_ENGINEER)
    mix = lookup.mix_design(mix_id)
    if mix["status"] != "SUSPENDED":
        errors.fail(errors.ERR_MIX_DESIGN_INVALID_STATE,
                    "Only a SUSPENDED mix design may be retired.")
    for run in db.store.bed_runs.values():
        if run["mix_design_id"] == mix["id"] and run["status"] in _LIVE_RUN_STATES:
            errors.fail(errors.ERR_MIX_DESIGN_INVALID_STATE,
                        "A bed run that is not STRIPPED still references this mix.")
    mix["status"] = "RETIRED"
    db.touch(mix)
    return response.object_response(serialize.mix_design(mix), 200)
