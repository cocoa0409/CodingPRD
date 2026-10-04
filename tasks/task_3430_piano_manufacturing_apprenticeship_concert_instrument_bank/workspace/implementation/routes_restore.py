"""Restoration case endpoints (PRD 3.7) and the authenticity guarantee."""
from flask import Blueprint, request

from auth import ALL_ROLES, authenticate
from calc import GRADE_BUMP, authenticity_pct, pct_passes
from db import STORE, new_entity, touch
from envelope import ok, paged
from errors import raise_err
from serialize import restoration as ser_case
from validate import get_body, opt_bool, opt_fk, req_int, req_str

bp = Blueprint("restorations", __name__, url_prefix="/piano-works")

WM = ("WorkshopManager",)
MC = ("MasterCraftsman",)
ADVANCE_TARGETS = ("DISASSEMBLED", "REBUILT")
LEGAL_NEXT = {"QUOTED": "DISASSEMBLED", "DISASSEMBLED": "REBUILT"}


def _get_case(rid):
    c = STORE["restorations"].get(rid)
    if c is None:
        raise_err("ERR_NOT_FOUND", "restoration case %s not found" % rid)
    return c


@bp.post("/restorations")
def create_case():
    authenticate(WM)
    body = get_body()
    inst_id = opt_fk(body, "instrument_id")
    if inst_id is None:
        raise_err("ERR_VALIDATION", "instrument_id is required")
    inst = STORE["instruments"].get(inst_id)
    if inst is None:
        raise_err("ERR_NOT_FOUND", "instrument %s not found" % inst_id)
    lead_id = opt_fk(body, "lead_craftsman_id")
    if lead_id is None:
        raise_err("ERR_VALIDATION", "lead_craftsman_id is required")
    if lead_id not in STORE["craftsmen"]:
        raise_err("ERR_NOT_FOUND", "lead craftsman %s not found" % lead_id)
    diagnosis = req_str(body, "diagnosis")
    authentic = req_int(body, "authentic_parts_value_cents", minimum=0)
    total = req_int(body, "total_parts_value_cents", minimum=0)
    if total < authentic:
        raise_err("ERR_VALIDATION", "total_parts_value_cents must be >= authentic_parts_value_cents")
    waiver = opt_bool(body, "waiver_accepted", False)
    if inst["status"] == "ON_LOAN":
        raise_err("ERR_INVALID_STATE", "cannot open a case against an ON_LOAN instrument")
    for c in STORE["restorations"].values():
        if c["instrument_id"] == inst_id and c["status"] != "COMPLETED":
            raise_err("ERR_RESTORATION_ALREADY_OPEN", "a non-COMPLETED case exists for this instrument")
    pct = authenticity_pct(authentic, total)
    case = new_entity()
    case.update({
        "instrument_id": inst_id,
        "lead_craftsman_id": lead_id,
        "origin": "MANUAL",
        "diagnosis": diagnosis,
        "status": "QUOTED",
        "authentic_parts_value_cents": authentic,
        "total_parts_value_cents": total,
        "waiver_accepted": waiver,
        "authenticity_pct": pct,
        "final_authentic_value_cents": None,
        "final_total_parts_value_cents": None,
    })
    STORE["restorations"][case["id"]] = case
    # Continuous threshold rule: sub-threshold quote without waiver self-holds.
    if total > 0 and not pct_passes(pct) and not waiver:
        case["status"] = "AUTHENTICITY_HOLD"
        touch(case)
    if inst["status"] in ("SHOWROOM", "BANK"):
        inst["status"] = "RESTORATION"
        touch(inst)
    return ok(ser_case(case), 201)


@bp.get("/restorations")
def list_cases():
    authenticate(ALL_ROLES)
    items = list(STORE["restorations"].values())
    for field in ("instrument_id", "lead_craftsman_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [c for c in items if c[field] == v]
    return paged(items, ser_case)


@bp.get("/restorations/<rid>")
def get_case(rid):
    authenticate(ALL_ROLES)
    return ok(ser_case(_get_case(rid)))


@bp.post("/restorations/<rid>/advance")
def advance_case(rid):
    authenticate(MC)
    case = _get_case(rid)
    body = get_body()
    to_stage = req_str(body, "to_stage")
    concern = opt_bool(body, "authenticity_concern", False)
    if to_stage not in ADVANCE_TARGETS:
        if to_stage in ("QUOTED", "AUTHENTICITY_HOLD", "COMPLETED"):
            raise_err("ERR_INVALID_STATE", "%s is not an advance target" % to_stage)
        raise_err("ERR_VALIDATION", "to_stage must be DISASSEMBLED or REBUILT")
    expected = LEGAL_NEXT.get(case["status"])
    if expected is None or expected != to_stage:
        raise_err("ERR_INVALID_STATE", "cannot advance from %s to %s" % (case["status"], to_stage))
    # authenticity_concern diverts the advance into AUTHENTICITY_HOLD.
    case["status"] = "AUTHENTICITY_HOLD" if concern else to_stage
    touch(case)
    return ok(ser_case(case))


@bp.post("/restorations/<rid>/resolve-authenticity")
def resolve_authenticity(rid):
    authenticate(MC)
    case = _get_case(rid)
    body = get_body()
    authentic = req_int(body, "authentic_parts_value_cents", minimum=0)
    total = req_int(body, "total_parts_value_cents", minimum=0)
    if total < authentic:
        raise_err("ERR_VALIDATION", "total_parts_value_cents must be >= authentic_parts_value_cents")
    waiver = opt_bool(body, "waiver_accepted", case["waiver_accepted"])
    if case["status"] != "AUTHENTICITY_HOLD":
        raise_err("ERR_INVALID_STATE", "only an AUTHENTICITY_HOLD case can be resolved")
    pct = authenticity_pct(authentic, total)
    if not (pct_passes(pct) or waiver):
        raise_err("ERR_AUTHENTICITY_BELOW_THRESHOLD", "authenticity below 70.0 without waiver")
    case["authentic_parts_value_cents"] = authentic
    case["total_parts_value_cents"] = total
    case["waiver_accepted"] = waiver
    case["authenticity_pct"] = pct
    case["status"] = "QUOTED"
    touch(case)
    return ok(ser_case(case))


@bp.post("/restorations/<rid>/complete")
def complete_case(rid):
    authenticate(MC)
    case = _get_case(rid)
    body = get_body()
    final_authentic = req_int(body, "final_authentic_value_cents", minimum=0)
    final_total = req_int(body, "final_total_parts_value_cents", minimum=0)
    if final_total < final_authentic:
        raise_err("ERR_VALIDATION", "final total must be >= final authentic value")
    if case["status"] != "REBUILT":
        raise_err("ERR_INVALID_STATE", "only a REBUILT case can be completed")
    # Pinned evaluation order (PRD 3.7).
    # (1) final authenticity percentage from the declared final values.
    final_pct = authenticity_pct(final_authentic, final_total)
    if final_total > 0 and not pct_passes(final_pct) and not case["waiver_accepted"]:
        raise_err("ERR_AUTHENTICITY_BELOW_THRESHOLD", "final authenticity below 70.0 without waiver")
    inst = STORE["instruments"][case["instrument_id"]]
    case["final_authentic_value_cents"] = final_authentic
    case["final_total_parts_value_cents"] = final_total
    case["authenticity_pct"] = final_pct
    case["status"] = "COMPLETED"
    touch(case)
    # (2) certified_authentic: unchanged when final total is zero.
    if final_total > 0:
        inst["certified_authentic"] = pct_passes(final_pct)
    # (3) grade bump uses the pre-completion grade.
    inst["condition_grade"] = GRADE_BUMP[inst["condition_grade"]]
    # (4) status uses the post-bump grade.
    if inst["certified_authentic"] and inst["condition_grade"] in ("A", "B"):
        inst["status"] = "BANK"
    else:
        inst["status"] = "SHOWROOM"
    touch(inst)
    return ok(ser_case(case))
