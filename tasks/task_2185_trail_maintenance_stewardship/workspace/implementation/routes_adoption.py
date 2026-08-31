"""Adoption agreements, seasonal work plans and the grant-match read."""

from flask import Blueprint, request

import calc
import domain
import store
import validation as v
from auth import ALL_ROLES, actor, require, role
from envelope import created, ok, paginate
from errors import fail
from store import new_entity, touch

bp = Blueprint("adoption", __name__)

AGREEMENT_STATUSES = ("DRAFT", "SUBMITTED", "RETURNED", "APPROVED", "ACTIVE",
                      "SUSPENDED", "TERMINATED")
PLAN_STATUSES = ("DRAFT", "SUBMITTED", "REVISION_REQUESTED", "APPROVED", "CLOSED")
BUDGET_POSTURES = ("HEALTHY", "TIGHT", "EXHAUSTED", "OVER_COMMITTED")
GRANT_VARIANTS = ("PROVISIONAL", "CERTIFIED")


def _enum_filter(name, allowed):
    value = request.args.get(name)
    if value is None:
        return None
    if value not in allowed:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' is not a declared member." % name)
    return value


def _segment_adopted(segment, excluding=None):
    for agreement in domain.agreements_of_segment(segment):
        if excluding is not None and agreement["id"] == excluding:
            continue
        if agreement["status"] in ("ACTIVE", "SUSPENDED"):
            return True
    return False


# ---------------------------------------------------------------------------
# AdoptionAgreement
# ---------------------------------------------------------------------------
@bp.post("/adoption-agreements")
@require("CrewLeader")
def create_agreement():
    data = v.body()
    trail_segment_id = v.req_id(data, "trail_segment_id")
    crew_leader_volunteer_id = v.req_id(data, "crew_leader_volunteer_id")
    term_start_date = v.req_date(data, "term_start_date")
    term_end_date = v.req_date(data, "term_end_date")
    if term_end_date <= term_start_date:
        fail("ERR_INVALID_REQUEST", "term_end_date must be strictly after term_start_date.")

    domain.get_segment(trail_segment_id)
    domain.get_volunteer(crew_leader_volunteer_id)

    agreement = new_entity({
        "trail_segment_id": trail_segment_id,
        "crew_leader_volunteer_id": crew_leader_volunteer_id,
        "term_start_date": store.fmt_date(term_start_date),
        "term_end_date": store.fmt_date(term_end_date),
        "status": "DRAFT",
        "suspension_reason": None,
        "revision_round": 0,
        "pinned_policy_version": None,
        "reviewed_by_user_id": None,
        "activated_at": None,
    })
    store.agreements[agreement["id"]] = agreement
    return created(domain.s_agreement(agreement))


@bp.get("/adoption-agreements/<entity_id>")
@require(*ALL_ROLES)
def read_agreement(entity_id):
    return ok(domain.s_agreement(domain.get_agreement(entity_id)))


@bp.get("/adoption-agreements")
@require(*ALL_ROLES)
def list_agreements():
    trail_segment_id = request.args.get("trail_segment_id")
    crew_leader_volunteer_id = request.args.get("crew_leader_volunteer_id")
    status = _enum_filter("status", AGREEMENT_STATUSES)
    rows = store.ordered(list(store.agreements.values()))
    if trail_segment_id is not None:
        rows = [r for r in rows if r["trail_segment_id"] == trail_segment_id]
    if crew_leader_volunteer_id is not None:
        rows = [r for r in rows if r["crew_leader_volunteer_id"] == crew_leader_volunteer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, domain.s_agreement)


@bp.post("/adoption-agreements/<entity_id>/submit")
@require("CrewLeader")
def submit_agreement(entity_id):
    agreement = domain.get_agreement(entity_id)
    if actor() != agreement["crew_leader_volunteer_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the signing crew leader may submit.")
    if agreement["status"] not in ("DRAFT", "RETURNED"):
        fail("ERR_INVALID_STATE", "Only a DRAFT or RETURNED agreement may be submitted.")

    segment = domain.get_segment(agreement["trail_segment_id"])
    if segment["posture"] == "INCIDENT_CLOSED":
        fail("ERR_SEGMENT_CLOSED", "The segment is closed by an incident.")

    leader = store.volunteers.get(agreement["crew_leader_volunteer_id"])
    if not domain.waiver_current(leader):
        fail("ERR_WAIVER_NOT_SIGNED", "The crew leader's waiver is not current.")

    if _segment_adopted(segment, excluding=agreement["id"]):
        fail("ERR_SEGMENT_ALREADY_ADOPTED", "The segment is already adopted.")

    if agreement["status"] == "RETURNED" and agreement["revision_round"] > calc.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "The revision ceiling has been reached.")

    agreement["status"] = "SUBMITTED"
    touch(agreement)
    return ok(domain.s_agreement(agreement))


@bp.post("/adoption-agreements/<entity_id>/review")
@require("StewardshipCoordinator")
def review_agreement(entity_id):
    agreement = domain.get_agreement(entity_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("APPROVE", "RETURN"))
    reason = None
    if decision == "RETURN":
        reason = v.req_str(data, "reason")
    if agreement["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED agreement may be reviewed.")

    segment = domain.get_segment(agreement["trail_segment_id"])
    if decision == "APPROVE":
        if _segment_adopted(segment, excluding=agreement["id"]):
            fail("ERR_SEGMENT_ALREADY_ADOPTED", "The segment is already adopted.")
        agreement["status"] = "APPROVED"
    else:
        agreement["status"] = "RETURNED"
        agreement["revision_round"] = int(agreement["revision_round"]) + 1
    agreement["reviewed_by_user_id"] = actor()
    touch(agreement)
    return ok(domain.s_agreement(agreement))


@bp.post("/adoption-agreements/<entity_id>/activate")
@require("LandManagerOfficer")
def activate_agreement(entity_id):
    agreement = domain.get_agreement(entity_id)
    segment = domain.get_segment(agreement["trail_segment_id"])
    if actor() != segment["land_manager_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the governing land manager may activate.")
    if agreement["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Only an APPROVED agreement may be activated.")

    today = store.clock_date()
    start = store.parse_date(agreement["term_start_date"])
    end = store.parse_date(agreement["term_end_date"])
    if not (start <= today <= end):
        fail("ERR_INVALID_STATE", "The logical clock date is outside the adoption term.")

    if segment["posture"] in ("INCIDENT_CLOSED", "SEASONAL_CLOSED"):
        fail("ERR_SEGMENT_CLOSED", "The segment is closed.")
    if _segment_adopted(segment, excluding=agreement["id"]):
        fail("ERR_SEGMENT_ALREADY_ADOPTED", "The segment is already adopted.")

    manager = domain.segment_manager(segment)
    agreement["status"] = "ACTIVE"
    agreement["pinned_policy_version"] = manager["policy_version"]
    agreement["activated_at"] = store.now_iso()
    agreement["suspension_reason"] = None
    touch(agreement)

    segment["adoption_status"] = "ADOPTED"
    touch(segment)
    manager["adopted_segment_count"] = int(manager["adopted_segment_count"]) + 1
    touch(manager)
    return ok(domain.s_agreement(agreement))


@bp.post("/adoption-agreements/<entity_id>/terminate")
@require("StewardshipCoordinator", "LandManagerOfficer")
def terminate_agreement(entity_id):
    agreement = domain.get_agreement(entity_id)
    segment = domain.get_segment(agreement["trail_segment_id"])
    acting_role = role()
    if acting_role == "LandManagerOfficer" and actor() != segment["land_manager_id"]:
        fail("ERR_NOT_RESOURCE_OWNER", "Only the governing land manager may terminate.")

    data = v.body()
    reason = v.req_str(data, "reason")

    if acting_role == "StewardshipCoordinator":
        if agreement["status"] != "ACTIVE":
            fail("ERR_INVALID_STATE", "A coordinator may only terminate an ACTIVE agreement.")
    else:
        if agreement["status"] != "SUSPENDED":
            fail("ERR_INVALID_STATE", "A land manager may only terminate a SUSPENDED agreement.")

    agreement["status"] = "TERMINATED"
    agreement["suspension_reason"] = None
    touch(agreement)

    segment["adoption_status"] = "UNADOPTED"
    touch(segment)
    manager = domain.segment_manager(segment)
    if manager is not None:
        manager["adopted_segment_count"] = max(0, int(manager["adopted_segment_count"]) - 1)
        touch(manager)

    for plan in domain.plans_of_agreement(agreement):
        if plan["status"] == "APPROVED":
            plan["status"] = "CLOSED"
            touch(plan)
    for party in domain.parties_of_agreement(agreement):
        if party["schedule_status"] in ("PLANNED", "CONFIRMED", "SUSPENDED"):
            party["schedule_status"] = "CANCELLED"
            touch(party)
    return ok(domain.s_agreement(agreement))


# ---------------------------------------------------------------------------
# WorkPlan
# ---------------------------------------------------------------------------
@bp.post("/work-plans")
@require("CrewLeader")
def create_plan():
    data = v.body()
    adoption_agreement_id = v.req_id(data, "adoption_agreement_id")
    season_year = v.req_int(data, "season_year")
    requested_budget_cents = v.req_int(data, "requested_budget_cents", minimum=0)

    agreement = domain.get_agreement(adoption_agreement_id)
    for row in store.plans.values():
        if (row["adoption_agreement_id"] == adoption_agreement_id
                and row["season_year"] == season_year):
            fail("ERR_INVALID_REQUEST",
                 "A plan already exists for this adoption and season year.")

    plan = new_entity({
        "adoption_agreement_id": adoption_agreement_id,
        "season_year": season_year,
        "requested_budget_cents": requested_budget_cents,
        "approved_budget_cents": 0,
        "committed_cents": 0,
        "spent_cents": 0,
        "available_cents": 0,
        "budget_posture": "HEALTHY",
        "status": "DRAFT",
        "revision_round": 0,
        "verified_volunteer_hours": 0,
        "certified_volunteer_hours": 0,
    })
    store.plans[plan["id"]] = plan
    return created(domain.s_plan(plan))


@bp.get("/work-plans/<entity_id>")
@require(*ALL_ROLES)
def read_plan(entity_id):
    return ok(domain.s_plan(domain.get_plan(entity_id)))


@bp.get("/work-plans")
@require(*ALL_ROLES)
def list_plans():
    adoption_agreement_id = request.args.get("adoption_agreement_id")
    status = _enum_filter("status", PLAN_STATUSES)
    budget_posture = _enum_filter("budget_posture", BUDGET_POSTURES)
    rows = store.ordered(list(store.plans.values()))
    if adoption_agreement_id is not None:
        rows = [r for r in rows if r["adoption_agreement_id"] == adoption_agreement_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if budget_posture is not None:
        rows = [r for r in rows if r["budget_posture"] == budget_posture]
    return paginate(rows, domain.s_plan)


@bp.post("/work-plans/<entity_id>/submit")
@require("CrewLeader")
def submit_plan(entity_id):
    plan = domain.get_plan(entity_id)
    if plan["status"] != "DRAFT":
        fail("ERR_INVALID_STATE", "Only a DRAFT work plan may be submitted.")
    if int(plan["requested_budget_cents"]) < 0:
        fail("ERR_INVALID_REQUEST", "requested_budget_cents must be at least 0.")
    agreement = domain.plan_agreement(plan)
    if agreement is None or agreement["status"] != "ACTIVE":
        fail("ERR_ADOPTION_NOT_ACTIVE", "The governing adoption is not ACTIVE.")
    if plan["revision_round"] > calc.MAX_REVISION_ROUNDS:
        fail("ERR_REVISION_LIMIT_EXCEEDED", "The revision ceiling has been reached.")

    plan["status"] = "SUBMITTED"
    touch(plan)
    return ok(domain.s_plan(plan))


@bp.post("/work-plans/<entity_id>/review")
@require("StewardshipCoordinator")
def review_plan(entity_id):
    plan = domain.get_plan(entity_id)
    data = v.body()
    decision = v.req_enum(data, "decision", ("APPROVE", "REQUEST_REVISION"))
    approved_budget_cents = None
    if decision == "APPROVE":
        approved_budget_cents = v.req_int(data, "approved_budget_cents", minimum=0)
    else:
        v.req_str(data, "reason")

    if plan["status"] != "SUBMITTED":
        fail("ERR_INVALID_STATE", "Only a SUBMITTED work plan may be reviewed.")

    if decision == "APPROVE":
        agreement = domain.plan_agreement(plan)
        if agreement is None or agreement["status"] != "ACTIVE":
            fail("ERR_ADOPTION_NOT_ACTIVE", "The governing adoption is not ACTIVE.")
        plan["status"] = "APPROVED"
        plan["approved_budget_cents"] = approved_budget_cents
        domain.recompute_ledger(plan)
        touch(plan)
        domain.propagate_budget(plan)
    else:
        plan["revision_round"] = int(plan["revision_round"]) + 1
        plan["status"] = "DRAFT"
        touch(plan)
    return ok(domain.s_plan(plan))


@bp.get("/work-plans/<entity_id>/grant-match")
@require("StewardshipCoordinator", "GrantsAdministrator")
def grant_match(entity_id):
    plan = domain.get_plan(entity_id)
    variant = request.args.get("variant")
    if variant is None:
        fail("ERR_INVALID_REQUEST", "Query parameter 'variant' is required.")
    if variant not in GRANT_VARIANTS:
        fail("ERR_INVALID_REQUEST", "variant must be PROVISIONAL or CERTIFIED.")

    included = []
    for party in domain.parties_of_plan(plan):
        for shift in domain.shifts_of_party(party):
            if variant == "PROVISIONAL":
                if shift["status"] in calc.PROVISIONAL_STATUSES:
                    included.append(shift)
            else:
                if shift["status"] == "HOURS_CERTIFIED":
                    included.append(shift)

    delivered = sum(o["total_cents"] for o in domain.orders_of_plan(plan)
                    if o["status"] == "DELIVERED")
    return ok(calc.grant_match(variant, included, delivered))
