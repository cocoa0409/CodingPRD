"""DeliveryMilestone routes + ESA auto-termination cascade."""
from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles, ALL_ROLES
from pagination import paginate
from response import success_object, success_list
from services import compute_ld, recompute_projection
from util import new_id, stamp_new, touch, req_enum, parse_iso

bp = Blueprint("milestones", __name__)

KINDS = {"DELIVERY", "COMMISSIONING"}


def serialize_milestone(m):
    return dict(m)


def get_milestone_or_404(mid):
    m = store.milestones.get(mid)
    if m is None:
        raise ApiError("ERR_NOT_FOUND", 404, "DeliveryMilestone not found")
    return m


def terminate_esa_cascade(esa):
    """EXECUTED -> TERMINATED with full cascade (milestones, orders, claims)."""
    esa["status"] = "TERMINATED"
    touch(esa)
    for m in store.milestones.values():
        if m["esa_id"] == esa["id"] and m["status"] == "SCHEDULED":
            m["status"] = "CANCELLED"
            touch(m)
    claims_of_esa = {c["id"]: c for c in store.claims.values() if c["esa_id"] == esa["id"]}
    for o in store.orders.values():
        if o.get("warranty_claim_id") in claims_of_esa and o["status"] == "ORDERED":
            o["status"] = "CANCELLED"
            if o.get("covered_by_credit"):
                sa = store.service_agreements.get(o["service_agreement_id"])
                if sa is not None:
                    sa["credit_drawn_cents"] -= o["part_cost_cents"]
                    touch(sa)
            touch(o)
    for c in claims_of_esa.values():
        if c["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            c["status"] = "REJECTED"
            touch(c)


@bp.route("/delivery-milestones", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def create_milestone():
    body = request.get_json(silent=True) or {}
    esa_id = body.get("esa_id")
    if not isinstance(esa_id, str) or esa_id not in store.esas:
        raise ApiError("ERR_ESA_NOT_FOUND", 404, "esa_id does not reference an existing EquipmentSupplyAgreement")
    esa = store.esas[esa_id]
    kind = req_enum(body, "kind", KINDS)
    planned_raw = body.get("planned_date")
    planned = parse_iso(planned_raw, "planned_date")
    # cross-entity state: ESA must be EXECUTED
    if esa["status"] != "EXECUTED":
        raise ApiError("ERR_ESA_NOT_EXECUTABLE_STATE", 409,
                       "Milestones can only be scheduled on an EXECUTED ESA")
    m = {
        "id": new_id(),
        "esa_id": esa_id,
        "kind": kind,
        "planned_date": planned_raw,
        "actual_date": None,
        "days_late": 0,
        "ld_applied_cents": 0,
        "ld_waived_cents": 0,
        "status": "SCHEDULED",
    }
    stamp_new(m)
    store.milestones[m["id"]] = m
    return success_object(serialize_milestone(m), 201)


@bp.route("/delivery-milestones", methods=["GET"])
@require_roles(set(ALL_ROLES))
def list_milestones():
    esa_id = request.args.get("esa_id")
    items = [m for m in store.milestones.values()
             if esa_id is None or m["esa_id"] == esa_id]
    page, limit, offset, total = paginate(items)
    return success_list([serialize_milestone(m) for m in page], limit, offset, total)


@bp.route("/delivery-milestones/<mid>", methods=["GET"])
@require_roles(set(ALL_ROLES))
def get_milestone(mid):
    return success_object(serialize_milestone(get_milestone_or_404(mid)))


@bp.route("/delivery-milestones/<mid>/record-outcome", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def record_outcome(mid):
    m = get_milestone_or_404(mid)
    if m["status"] != "SCHEDULED":
        raise ApiError("ERR_MILESTONE_NOT_SCHEDULED", 409, "Milestone must be SCHEDULED")
    body = request.get_json(silent=True) or {}
    outcome = body.get("outcome")
    actual_raw = body.get("actual_date")
    # Temporal/business check first (priority 6/7): outcome-vs-date agreement uses the parsed date.
    actual = parse_iso(actual_raw, "actual_date")
    planned = parse_iso(m["planned_date"], "planned_date")
    if outcome == "ACHIEVED":
        if actual > planned:
            raise ApiError("ERR_MILESTONE_OUTCOME_MISMATCH", 409,
                           "ACHIEVED requires actual_date <= planned_date")
    elif outcome == "MISSED":
        if actual <= planned:
            raise ApiError("ERR_MILESTONE_OUTCOME_MISMATCH", 409,
                           "MISSED requires actual_date > planned_date")
    else:
        # operation-payload shape error, evaluated after state/business checks
        raise ApiError("ERR_INVALID_REQUEST", 400, "outcome must be ACHIEVED or MISSED")

    esa = store.esas.get(m["esa_id"])
    m["actual_date"] = actual_raw
    if outcome == "ACHIEVED":
        m["status"] = "ACHIEVED"
        m["days_late"] = 0
        m["ld_applied_cents"] = 0
        if m["kind"] == "COMMISSIONING":
            project = store.projects.get(esa["project_id"])
            if project is not None and not project.get("commissioned_capacity_mwh"):
                project["commissioned_capacity_mwh"] = esa["contracted_energy_mwh"]
                recompute_projection(project)
                touch(project)
    else:
        m["status"] = "MISSED"
        # whole calendar days from planned_date (exclusive) to actual_date (inclusive)
        delta = actual - planned
        days_late = delta.days
        if (delta.seconds or delta.microseconds) or delta.days < 0:
            # any crossing into a new calendar day counts as a full day
            days_late = delta.days + (1 if (delta.seconds or delta.microseconds) else 0)
        days_late = max(0, days_late)
        m["days_late"] = days_late
        ld = compute_ld(esa, m, days_late)
        m["ld_applied_cents"] = ld
        esa["accrued_ld_cents"] += ld
        esa["net_ld_due_cents"] = esa["accrued_ld_cents"] - esa["waived_ld_cents"]
        touch(esa)
        if (esa["ld_cap_cents"] > 0 and esa["accrued_ld_cents"] == esa["ld_cap_cents"]
                and esa["status"] == "EXECUTED"):
            terminate_esa_cascade(esa)
    touch(m)
    return success_object(serialize_milestone(m))


@bp.route("/delivery-milestones/<mid>/cancel", methods=["POST"])
@require_roles({"ProjectDeveloper"})
def cancel_milestone(mid):
    m = get_milestone_or_404(mid)
    if m["status"] != "SCHEDULED":
        raise ApiError("ERR_MILESTONE_NOT_SCHEDULED", 409, "Milestone must be SCHEDULED")
    esa = store.esas.get(m["esa_id"])
    if esa["status"] not in ("DRAFT", "EXECUTED"):
        raise ApiError("ERR_ESA_TERMINAL_MILESTONE_LOCKED", 409,
                       "Milestone cancel requires the ESA in DRAFT or EXECUTED")
    m["status"] = "CANCELLED"
    touch(m)
    return success_object(serialize_milestone(m))
