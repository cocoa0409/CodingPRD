"""Closure plans and closure-deadline extension requests."""
from flask import Blueprint

import calc
import common
import derive
import envelope
import shape
import store
from errors import ApiError
from guards import authenticate, require_discipline, require_license_active
from routes_units import CODE_RE

bp = Blueprint("closure", __name__)

PLAN_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "plan_code": {"t": "str", "req": True, "min": 3, "max": 20, "re": CODE_RE},
    "selected_method": {"t": "enum", "req": True,
                        "vals": ("CLOSURE_IN_PLACE", "CLOSURE_BY_REMOVAL")},
    "in_place_capital_usd_cents": {"t": "int", "req": True, "min": 1},
    "in_place_annual_care_usd_cents": {"t": "int", "req": True, "min": 1},
    "removal_capital_usd_cents": {"t": "int", "req": True, "min": 1},
    "removal_annual_care_usd_cents": {"t": "int", "req": True, "min": 1},
    "care_period_years": {"t": "int", "req": True, "min": 1, "max": 50},
    "selection_justification": {"t": "str", "min": 1, "max": 500},
}

JUSTIFICATION_MIN_CHARS = 30


def _require_justification(plan):
    if plan["selected_method"] == plan["recommended_method"]:
        return
    text = plan["selection_justification"]
    if text is None or len(text) < JUSTIFICATION_MIN_CHARS:
        raise ApiError("ERR_METHOD_JUSTIFICATION_REQUIRED",
                       "A selection_justification of at least 30 characters is "
                       "required when the selected method differs from the "
                       "recommended method.")


def _recost(plan, unit):
    totals = calc.closure_cost_present_value(plan)
    plan.update(totals)
    plan["recommended_method"] = calc.closure_method_recommendation(unit, totals)


@bp.post("/ccr/closure-plans")
def create_plan():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(PLAN_SPEC)
    unit = common.get_unit(data["unit_id"])
    common.unique_code(store.closure_plans, "plan_code", data["plan_code"],
                       "unit_id", unit["id"])
    common.unit_not_care_complete(unit)
    plan = dict(data)
    plan["engineering_certified_by"] = None
    plan["cost_certified_by"] = None
    plan["status"] = "DRAFT"
    plan["engineering_certified_on"] = None
    plan["cost_certified_on"] = None
    plan["design_narrative"] = None
    plan["cost_basis_note"] = None
    plan["approved_on"] = None
    plan["permit_reference"] = None
    plan["return_count"] = 0
    derive.refresh_unit(unit)
    _recost(plan, unit)
    _require_justification(plan)
    store.stamp_new(plan)
    store.closure_plans[plan["id"]] = plan
    return envelope.created(derive.plan(plan))


ENGINEERING_SPEC = {
    "certified_on": {"t": "date", "req": True},
    "design_narrative": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/closure-plans/<plan_id>/engineering-certification")
def engineering_certification(plan_id):
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(ENGINEERING_SPEC)
    plan = common.get_plan(plan_id)
    unit = common.get_unit(plan["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_ENGINEERING)
    common.unit_not_care_complete(unit)
    if plan["status"] not in ("DRAFT", "COST_CERTIFIED"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "The plan does not accept an engineering certification.")
    common.segregation(actor.user_id, plan["cost_certified_by"])
    derive.refresh_unit(unit)
    if unit["governing_stability_verdict"] != "ADEQUATE":
        raise ApiError("ERR_STABILITY_NOT_ADEQUATE",
                       "The unit's governing stability verdict is not ADEQUATE.")
    plan["engineering_certified_by"] = actor.user_id
    plan["engineering_certified_on"] = data["certified_on"]
    plan["design_narrative"] = data["design_narrative"]
    plan["status"] = ("FULLY_CERTIFIED" if plan["status"] == "COST_CERTIFIED"
                      else "ENGINEERING_CERTIFIED")
    store.touch(plan)
    return envelope.ok(derive.plan(plan))


COST_SPEC = {
    "certified_on": {"t": "date", "req": True},
    "cost_basis_note": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/closure-plans/<plan_id>/cost-certification")
def cost_certification(plan_id):
    actor = authenticate(("ProfessionalEngineer",))
    data = shape.read_body(COST_SPEC)
    plan = common.get_plan(plan_id)
    unit = common.get_unit(plan["unit_id"])
    require_license_active(actor)
    require_discipline(actor, common.D_COST)
    common.unit_not_care_complete(unit)
    if plan["status"] not in ("DRAFT", "ENGINEERING_CERTIFIED"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "The plan does not accept a cost certification.")
    common.segregation(actor.user_id, plan["engineering_certified_by"])
    plan["cost_certified_by"] = actor.user_id
    plan["cost_certified_on"] = data["certified_on"]
    plan["cost_basis_note"] = data["cost_basis_note"]
    derive.refresh_unit(unit)
    _recost(plan, unit)
    plan["status"] = ("FULLY_CERTIFIED"
                      if plan["status"] == "ENGINEERING_CERTIFIED"
                      else "COST_CERTIFIED")
    store.touch(plan)
    return envelope.ok(derive.plan(plan))


APPROVE_SPEC = {
    "approved_on": {"t": "date", "req": True},
    "permit_reference": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/closure-plans/<plan_id>/approve")
def approve_plan(plan_id):
    authenticate(("Regulator",))
    data = shape.read_body(APPROVE_SPEC)
    plan = common.get_plan(plan_id)
    unit = common.get_unit(plan["unit_id"])
    common.unit_not_care_complete(unit)
    if plan["status"] != "FULLY_CERTIFIED":
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Only a FULLY_CERTIFIED plan may be approved.")
    common.not_frozen(unit)
    derive.refresh_unit(unit)
    if (plan["selected_method"] == "CLOSURE_IN_PLACE"
            and unit["location_restriction_verdict"] == "DISQUALIFIED"):
        raise ApiError("ERR_LOCATION_RESTRICTION_DISQUALIFIED",
                       "A disqualified unit cannot be closed in place.")
    program = calc.unit_program(unit["id"])
    if (plan["selected_method"] == "CLOSURE_IN_PLACE" and program is not None
            and program["phase"] == "CORRECTIVE_ACTION"):
        raise ApiError("ERR_REMEDY_REQUIRES_REMOVAL",
                       "A unit under corrective action cannot be closed in place.")
    _require_justification(plan)
    plan["status"] = "APPROVED"
    plan["approved_on"] = data["approved_on"]
    plan["permit_reference"] = data["permit_reference"]
    store.touch(plan)
    if unit["closure_state"] == "ACTIVE":
        unit["closure_state"] = "CLOSURE_PLANNED"
    unit["closure_plan_posting_due_date"] = store.add_days(
        data["approved_on"], calc.CLOSURE_PLAN_POSTING_WINDOW_DAYS)
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.plan(plan))


@bp.post("/ccr/closure-plans/<plan_id>/return-to-draft")
def return_to_draft(plan_id):
    authenticate(("Regulator",))
    shape.read_body({})
    plan = common.get_plan(plan_id)
    unit = common.get_unit(plan["unit_id"])
    common.unit_not_care_complete(unit)
    if plan["status"] not in ("ENGINEERING_CERTIFIED", "COST_CERTIFIED",
                              "FULLY_CERTIFIED"):
        raise ApiError("ERR_INVALID_PLAN_STATE",
                       "Only a certified plan may be returned to draft.")
    plan["engineering_certified_by"] = None
    plan["engineering_certified_on"] = None
    plan["design_narrative"] = None
    plan["cost_certified_by"] = None
    plan["cost_certified_on"] = None
    plan["cost_basis_note"] = None
    plan["status"] = "DRAFT"
    plan["return_count"] = plan["return_count"] + 1
    store.touch(plan)
    return envelope.ok(derive.plan(plan))


EXTENSION_SPEC = {
    "unit_id": {"t": "id", "req": True},
    "requested_months": {"t": "int", "req": True, "min": 1, "max": 24},
    "justification_category": {"t": "enum", "req": True,
                               "vals": ("NO_ALTERNATIVE_CAPACITY",
                                        "PERMANENT_CESSATION",
                                        "TECHNICAL_INFEASIBILITY")},
    "narrative": {"t": "str", "req": True, "min": 1, "max": 500},
}


@bp.post("/ccr/extension-requests")
def create_extension():
    authenticate(("UtilityAdmin",))
    data = shape.read_body(EXTENSION_SPEC)
    unit = common.get_unit(data["unit_id"])
    common.unit_state(unit, ("ACTIVE",))
    common.not_frozen(unit)
    record = dict(data)
    record["status"] = "REQUESTED"
    record["granted_months"] = 0
    record["decided_on"] = None
    record["decision_note"] = None
    record["rescinded_on"] = None
    record["rescission_reason"] = None
    store.stamp_new(record)
    store.extension_requests[record["id"]] = record
    unit["extension_demonstration_due_date"] = store.add_days(
        store.fmt_date(store.today()), calc.EXTENSION_DEMONSTRATION_WINDOW_DAYS)
    store.touch(unit)
    common.settle(unit)
    return envelope.created(derive.extension(record))


DECISION_SPEC = {
    "decision": {"t": "enum", "req": True, "vals": ("GRANT", "DENY")},
    "granted_months": {"t": "int", "min": 0, "max": 24},
    "decided_on": {"t": "date", "req": True},
    "decision_note": {"t": "str", "min": 1, "max": 500},
}


@bp.post("/ccr/extension-requests/<request_id>/decision")
def decide_extension(request_id):
    authenticate(("Regulator",))
    data = shape.read_body(DECISION_SPEC)
    record = common.get_extension(request_id)
    unit = common.get_unit(record["unit_id"])
    common.unit_not_care_complete(unit)
    if record["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_EXTENSION_STATE",
                       "Only a REQUESTED extension may be decided.")
    common.not_frozen(unit)
    if data["decision"] == "GRANT":
        months = data["granted_months"] or 0
        posting = None
        for row in store.ordered(store.public_postings.values()):
            if (row["unit_id"] == unit["id"]
                    and row["posting_type"] == "EXTENSION_DEMONSTRATION"
                    and row["status"] == "POSTED"):
                posting = row
                break
        if posting is None:
            raise ApiError("ERR_EXTENSION_DEMONSTRATION_MISSING",
                           "No POSTED extension demonstration exists for the unit.")
        if posting["community_meeting_held_on"] is None:
            raise ApiError("ERR_COMMUNITY_ENGAGEMENT_INCOMPLETE",
                           "The extension demonstration records no community "
                           "meeting.")
        if months > record["requested_months"]:
            raise ApiError("ERR_GRANT_EXCEEDS_REQUEST",
                           "granted_months exceeds the requested months.")
        cap = calc.EXTENSION_CAP_MONTHS[unit["unit_type"]]
        if unit["granted_extension_months"] + months > cap:
            raise ApiError("ERR_EXTENSION_CAP_EXCEEDED",
                           "The cumulative extension exceeds the statutory cap.")
        record["status"] = "GRANTED"
        record["granted_months"] = months
        record["decided_on"] = data["decided_on"]
        record["decision_note"] = data["decision_note"]
        store.touch(record)
        unit["granted_extension_months"] = (unit["granted_extension_months"]
                                            + months)
        unit["closure_deadline_date"] = calc.closure_deadline_date(unit)
        store.touch(unit)
        common.settle(unit)
        return envelope.ok(derive.extension(record))
    record["status"] = "DENIED"
    record["decided_on"] = data["decided_on"]
    record["decision_note"] = data["decision_note"]
    store.touch(record)
    common.settle(unit)
    return envelope.ok(derive.extension(record))


RESCIND_SPEC = {
    "rescinded_on": {"t": "date", "req": True},
    "rescission_reason": {"t": "str", "req": True, "min": 1},
}


@bp.post("/ccr/extension-requests/<request_id>/rescind")
def rescind_extension(request_id):
    authenticate(("Regulator",))
    data = shape.read_body(RESCIND_SPEC)
    record = common.get_extension(request_id)
    unit = common.get_unit(record["unit_id"])
    common.unit_state(unit, ("ACTIVE",))
    if record["status"] != "GRANTED":
        raise ApiError("ERR_INVALID_EXTENSION_STATE",
                       "Only a GRANTED extension may be rescinded.")
    months = record["granted_months"]
    record["status"] = "RESCINDED"
    record["granted_months"] = 0
    record["rescinded_on"] = data["rescinded_on"]
    record["rescission_reason"] = data["rescission_reason"]
    store.touch(record)
    unit["granted_extension_months"] = max(
        0, unit["granted_extension_months"] - months)
    unit["closure_deadline_date"] = calc.closure_deadline_date(unit)
    store.touch(unit)
    common.settle(unit)
    return envelope.ok(derive.extension(record))
