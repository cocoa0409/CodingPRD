"""Review cycles: open, list, read, advance, record federal compliance (§3.3)."""
from flask import Blueprint, request

import constants as C
from auth import (authenticate, check_liaison_chain, require_role)
from calculations import federal_compliance_verdict
from db import STORE
from errors import (ERR_CYCLE_ALREADY_OPEN, ERR_CYCLE_PREREQUISITE_NOT_MET,
                    ERR_INSTITUTION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_REVIEW_CYCLE_NOT_FOUND, ERR_VALIDATION, raise_err)
from helpers import (fetch_or_404, get_body, new_entity, paginate, req_enum,
                     req_list, req_number, req_string, serialize, touch)
from response import success_list, success_object

bp = Blueprint("cycles", __name__)


@bp.post("/accreditation/institutions/<inst_id>/review-cycles")
def create_cycle(inst_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    inst = fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    body = get_body()
    cycle_type = req_enum(body, "cycle_type", C.CYCLE_TYPES)
    # Type must match institutional standing (PRD §3.3, checked first).
    if cycle_type == "INITIAL_ACCREDITATION" and inst["accreditation_status"] != "CANDIDATE":
        raise_err(ERR_INVALID_STATE, "INITIAL_ACCREDITATION requires a CANDIDATE institution")
    if cycle_type == "REAFFIRMATION" and inst["accreditation_status"] != "ACCREDITED":
        raise_err(ERR_INVALID_STATE, "REAFFIRMATION requires an ACCREDITED institution")
    for existing in STORE.review_cycles.values():
        if existing["institution_id"] == inst_id and existing["status"] != "CLOSED":
            raise_err(ERR_CYCLE_ALREADY_OPEN, "Institution already has a non-CLOSED cycle")
    cycle = new_entity({
        "institution_id": inst_id,
        "cycle_type": cycle_type,
        "status": "SCHEDULED",
        "federal_compliance_status": "PENDING",
        "federal_components": [],
        "cohort_default_rates": [],
        "decided_at": None,
    })
    STORE.review_cycles[cycle["id"]] = cycle
    return success_object(serialize(cycle), code=201)


@bp.get("/accreditation/institutions/<inst_id>/review-cycles")
def list_cycles(inst_id):
    actor = authenticate()
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, inst_id)
    fetch_or_404(STORE.institutions, inst_id, ERR_INSTITUTION_NOT_FOUND)
    items = [c for c in STORE.review_cycles.values() if c["institution_id"] == inst_id]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, total, limit, offset = paginate(items)
    return success_list(page, total, limit, offset)


@bp.get("/accreditation/review-cycles/<cycle_id>")
def get_cycle(cycle_id):
    actor = authenticate()
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    if actor.role == "InstitutionLiaison":
        check_liaison_chain(actor, cycle["institution_id"])
    return success_object(serialize(cycle))


@bp.post("/accreditation/review-cycles/<cycle_id>/advance")
def advance_cycle(cycle_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    status = cycle["status"]
    if status == "SCHEDULED":
        cycle["status"] = "MATERIALS_OPEN"
    elif status == "MATERIALS_OPEN":
        ok = any(a["review_cycle_id"] == cycle_id and a["status"] in ("SUBMITTED", "REVIEW_LOCKED")
                 for a in STORE.assurance_arguments.values())
        if not ok:
            raise_err(ERR_CYCLE_PREREQUISITE_NOT_MET,
                      "A SUBMITTED or REVIEW_LOCKED assurance argument is required")
        cycle["status"] = "EVALUATION_ACTIVE"
    elif status == "EVALUATION_ACTIVE":
        ok = any(t["review_cycle_id"] == cycle_id and t["status"] == "REPORT_FILED"
                 for t in STORE.review_teams.values())
        if not ok:
            raise_err(ERR_CYCLE_PREREQUISITE_NOT_MET, "A REPORT_FILED review team is required")
        cycle["status"] = "VISIT_COMPLETE"
    elif status == "VISIT_COMPLETE":
        ok = any(p["review_cycle_id"] == cycle_id and p["status"] == "CONVENED"
                 for p in STORE.decision_panels.values())
        if not ok:
            raise_err(ERR_CYCLE_PREREQUISITE_NOT_MET, "A CONVENED decision panel is required")
        cycle["status"] = "PANEL_REVIEW"
    elif status == "PANEL_REVIEW":
        # PANEL_REVIEW -> DECIDED is never taken via advance (§3.3).
        raise_err(ERR_INVALID_STATE, "This step happens only as a cascade of panel close")
    elif status == "DECIDED":
        ok = any(o["review_cycle_id"] == cycle_id and o["origin"] == "PANEL"
                 and o["status"] == "EFFECTIVE"
                 for o in STORE.action_outcomes.values())
        if not ok:
            raise_err(ERR_CYCLE_PREREQUISITE_NOT_MET,
                      "The deciding panel's outcome must be EFFECTIVE")
        cycle["status"] = "CLOSED"
    else:  # CLOSED
        raise_err(ERR_INVALID_STATE, "Cycle is terminal")
    touch(cycle)
    return success_object(serialize(cycle))


@bp.post("/accreditation/review-cycles/<cycle_id>/record-federal-compliance")
def record_federal_compliance(cycle_id):
    actor = authenticate()
    require_role(actor, ["CommissionStaff"])
    cycle = fetch_or_404(STORE.review_cycles, cycle_id, ERR_REVIEW_CYCLE_NOT_FOUND)
    body = get_body()
    components = req_list(body, "federal_components")
    for comp in components:
        if not isinstance(comp, dict):
            raise_err(ERR_VALIDATION, "Each federal component must be an object")
        comp["component_code"] = req_string(comp, "component_code")
        comp["result"] = req_enum(comp, "result", ["PASS", "FAIL"])
    rates = req_list(body, "cohort_default_rates")
    if len(rates) > C.CDR_MAX_RATES:
        raise_err(ERR_VALIDATION, "At most three cohort default rates may be recorded")
    for r in rates:
        if isinstance(r, bool) or not isinstance(r, (int, float)):
            raise_err(ERR_VALIDATION, "Cohort default rates must be numbers")
    verdict = federal_compliance_verdict(components, rates)
    cycle["federal_components"] = [{"component_code": c["component_code"], "result": c["result"]}
                                   for c in components]
    cycle["cohort_default_rates"] = list(rates)
    cycle["federal_compliance_status"] = verdict
    touch(cycle)
    return success_object(serialize(cycle))
