"""CorrectiveActionPlan endpoints (PRD §3.7, §4).

A plan is never created by direct request — it comes into existence as a
cascade of a clinical image review that returned a deficiency or a failure.
"""

import flask

import db
import response
from errors import fail
from middleware import require
from services import common


def _evidence_is_stale(unit, issued_at):
    """True when the unit holds scored phantom tests and every one predates
    the deficiency the plan answers."""
    scored = [t for t in common.unit_phantom_tests(unit["id"]) if t["result_status"] in ("SCORED", "PASS")]
    if not scored:
        return False
    for test in scored:
        scored_at = test.get("scored_at")
        if scored_at is not None and db.parse_ts(scored_at) >= issued_at:
            return False
    return True


def _recount(unit):
    """Recompute the open-deficiency count without writing the unit aggregate."""
    before = (unit["version"], unit["updated_at"])
    common.recompute_deficiency_open_count(unit)
    unit["version"], unit["updated_at"] = before


def _refresh(plan):
    common.recompute_deadline_status(plan)


def _source_unit(plan):
    source = db.SUBMISSIONS.get(plan["source_submission_id"])
    if source is None:
        return None, None
    return source, db.MODALITY_UNITS.get(source["unit_id"])


def register_routes(app):

    @app.route("/accreditation/corrective-action-plans", methods=["GET"])
    @require(["Any"])
    def list_plans(principal):
        for plan in db.PLANS.values():
            _refresh(plan)
        rows = list(db.PLANS.values())
        for field in ("facility_id", "source_submission_id", "plan_status", "deadline_status"):
            wanted = flask.request.args.get(field)
            if wanted:
                rows = [r for r in rows if r.get(field) == wanted]
        rows.sort(key=lambda r: r["created_at"])
        page, meta = response.paginate(rows, flask.request.args)
        return response.ok(common.serialize_many(page), 200, meta)

    @app.route("/accreditation/corrective-action-plans/<plan_id>", methods=["GET"])
    @require(["Any"])
    def read_plan(principal, plan_id):
        plan = common.get_plan(plan_id)
        _refresh(plan)
        return response.ok(common.serialize(plan))

    @app.route("/accreditation/corrective-action-plans/<plan_id>/submit", methods=["POST"])
    @require(["FacilityAdmin"])
    def submit_plan(principal, plan_id):
        plan = common.get_plan(plan_id)

        if plan["plan_status"] in ("ACCEPTED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "the plan has already reached a terminal state")
        if plan["plan_status"] != "OPEN":
            fail("ERR_INVALID_STATE", "the plan is not OPEN")

        facility = db.FACILITIES.get(plan["facility_id"])
        if facility is not None:
            common.recompute_all_deadline_statuses(facility["id"])
            if common.has_overdue_plan(facility["id"]):
                fail("ERR_DEADLINE_OVERDUE", "the facility holds an overdue corrective action plan")

        source, unit = _source_unit(plan)
        if source is None or source["review_status"] != "DEFICIENCY":
            fail("ERR_INVALID_STATE", "the source submission is not in DEFICIENCY")
        if unit is None:
            fail("ERR_UNIT_NOT_FOUND", "the source submission's unit does not resolve")
        if not common.unit_active_or_oos_equipment_exists(unit["id"]):
            fail("ERR_INVALID_STATE", "the source unit has no serviceable equipment")

        _refresh(plan)
        if plan["deadline_status"] == "OVERDUE":
            fail("ERR_DEADLINE_OVERDUE", "the plan's response deadline has passed")

        # The plan cannot be answered with phantom evidence that predates the
        # deficiency it answers. The refusal bites only when the unit does hold
        # phantom evidence and none of it postdates the deficiency; a unit with
        # no evidence to judge has nothing that predates anything.
        issued_at = db.parse_ts(source["deficiency_issued_at"])
        if _evidence_is_stale(unit, issued_at):
            fail("ERR_PHANTOM_UNSCORED", "the unit's phantom evidence predates the deficiency")

        stamp = db.now()
        common.set_field(plan, "plan_status", "SUBMITTED", stamp)
        plan["due_at"] = db.extend_deadline(plan["due_at"], 1)
        common.recompute_deadline_status(plan)
        _recount(unit)
        return response.ok(common.serialize(plan))

    @app.route("/accreditation/corrective-action-plans/<plan_id>/accept", methods=["POST"])
    @require(["AccreditationBody"])
    def accept_plan(principal, plan_id):
        plan = common.get_plan(plan_id)

        if plan["plan_status"] in ("ACCEPTED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "the plan has already reached a terminal state")
        if plan["plan_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "the plan is not SUBMITTED")

        source, unit = _source_unit(plan)
        supported = False
        if source is not None and source["review_status"] == "ACCEPTED":
            supported = True
        elif common.plan_resubmission_round_has_status(plan, ("ACCEPTED",)):
            supported = True
        if not supported:
            fail("ERR_INVALID_STATE", "no accepted evidence answers this plan")

        stamp = db.now()
        common.set_field(plan, "plan_status", "ACCEPTED", stamp)
        if unit is not None:
            _recount(unit)
        facility = db.FACILITIES.get(plan["facility_id"])
        if facility is not None and unit is not None and unit["deficiency_open_count"] == 0:
            if all(u["deficiency_open_count"] == 0 for u in common.facility_units(facility["id"])):
                facility["payer_participation_status"] = "ACTIVE"
        return response.ok(common.serialize(plan))

    @app.route("/accreditation/corrective-action-plans/<plan_id>/reject", methods=["POST"])
    @require(["AccreditationBody"])
    def reject_plan(principal, plan_id):
        plan = common.get_plan(plan_id)

        if plan["plan_status"] in ("ACCEPTED", "EXPIRED"):
            fail("ERR_ALREADY_TERMINAL", "the plan has already reached a terminal state")
        if plan["plan_status"] != "SUBMITTED":
            fail("ERR_INVALID_STATE", "the plan is not SUBMITTED")

        if not common.plan_resubmission_round_has_status(plan, ("DEFICIENCY", "FAILED")):
            fail("ERR_INVALID_STATE", "no deficient resubmission answers this plan")

        stamp = db.now()
        common.set_field(plan, "plan_status", "OPEN", stamp)
        plan["resubmission_attempts"] = plan["resubmission_attempts"] + 1
        plan["due_at"] = db.extend_deadline(plan["due_at"], 30)
        if plan.get("resubmission_deadline_at") is not None:
            plan["resubmission_deadline_at"] = db.extend_deadline(plan["resubmission_deadline_at"], 30)
        common.recompute_deadline_status(plan)
        _source, unit = _source_unit(plan)
        if unit is not None:
            _recount(unit)
        return response.ok(common.serialize(plan))