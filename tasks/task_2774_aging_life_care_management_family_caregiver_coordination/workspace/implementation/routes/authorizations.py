"""Service authorizations: two independent state dimensions on one record."""
from flask import Blueprint

import auth
import derive
import envelope
import lookup
import serialize
import validators as v
from errors import ApiError
from store import db, new_record, ordered, touch

bp = Blueprint("authorizations", __name__)

AUTH_STATUSES = ("PROPOSED", "AUTHORIZED", "ACTIVE", "SUSPENDED", "TERMINATED")
COI_STATUSES = ("NOT_REQUIRED", "PENDING_DISCLOSURE", "DISCLOSED",
                "ACKNOWLEDGED")
COI_ACTIONS = ("DISCLOSE", "ACKNOWLEDGE")
ELIGIBLE_ACK_ROLES = ("POA_HEALTHCARE", "POA_FINANCIAL", "GUARDIAN",
                      "RESPONSIBLE_PARTY")

OWNERSHIP = {
    "AUTHORIZED": (auth.ROLE_SUPERVISOR,),
    "ACTIVE": (auth.ROLE_CARE_MANAGER,),
    "SUSPENDED": (auth.ROLE_CARE_MANAGER,),
    "TERMINATED": (auth.ROLE_CARE_MANAGER,),
}

COI_OWNERSHIP = {
    "DISCLOSE": (auth.ROLE_CARE_MANAGER,),
    "ACKNOWLEDGE": (auth.ROLE_FAMILY,),
}

FILTERS = {
    "client_id": "client_id",
    "care_plan_id": "care_plan_id",
    "vendor_id": "vendor_id",
    "authorizing_decision_id": "authorizing_decision_id",
    "coi_acknowledged_by_contact_id": "coi_acknowledged_by_contact_id",
    "auth_status": "auth_status",
    "coi_status": "coi_status",
}

DISCLOSURE_TEMPLATE = (
    "The practice has a referral relationship with %s and may receive "
    "consideration of %s percent of this vendor's billings. This disclosure "
    "requires acknowledgement by a surrogate family decision maker."
)


@bp.route("/care/service-authorizations", methods=["POST"])
def create_authorization():
    auth.actor_for(auth.ROLE_CARE_MANAGER)
    body = v.json_body()
    care_plan_id = v.req_str(body, "care_plan_id", 1, None)
    vendor_id = v.req_str(body, "vendor_id", 1, None)
    expected_care_plan_version = v.req_int(body, "expected_care_plan_version", 1)
    coverage_start = v.req_dt(body, "coverage_start")
    coverage_end = v.req_dt(body, "coverage_end")
    if coverage_end <= coverage_start:
        raise v.bad("'coverage_end' must be strictly later than "
                    "'coverage_start'.")
    concurrent_caregivers = v.req_int(body, "concurrent_caregivers", 1, 10)
    hourly_cost_cents = v.req_int(body, "hourly_cost_cents", 1)
    authorizing_decision_id = v.opt_str(body, "authorizing_decision_id")
    vendor = lookup.need_vendor(vendor_id)
    plan = lookup.need_care_plan(care_plan_id)
    decision = None
    if authorizing_decision_id is not None:
        decision = lookup.need_decision(authorizing_decision_id)
    if expected_care_plan_version != plan["version"]:
        raise ApiError("ERR_STALE_CARE_PLAN_VERSION",
                       "The care plan has moved on since it was last read.")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE",
                       "An engagement may only be proposed under an ACTIVE "
                       "care plan.")
    if vendor["standing"] == "BARRED":
        raise ApiError("ERR_VENDOR_BARRED",
                       "A barred vendor may not be named on an authorization.")
    client = db.clients[plan["client_id"]]
    if decision is not None:
        conference = db.conferences.get(decision["family_conference_id"])
        if decision["status"] != "RATIFIED" or conference is None or \
                conference["client_id"] != client["id"]:
            raise ApiError("ERR_ENTITY_RELATIONSHIP_INVALID",
                           "The authorizing decision must be a RATIFIED "
                           "decision of this client's family conference.")
    coverage_hours = derive.coverage_hours_of(coverage_start, coverage_end,
                                              concurrent_caregivers)
    costs = derive.coordination_costs(coverage_hours, hourly_cost_cents)
    if vendor["has_referral_relationship"]:
        coi_status = "PENDING_DISCLOSURE"
        disclosure_text = DISCLOSURE_TEMPLATE % (
            vendor["name"], vendor["referral_fee_pct"])
    else:
        coi_status = "NOT_REQUIRED"
        disclosure_text = None
    record = new_record({
        "care_plan_id": care_plan_id,
        "vendor_id": vendor_id,
        "client_id": client["id"],
        "authorizing_decision_id": authorizing_decision_id,
        "coi_acknowledged_by_contact_id": None,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "concurrent_caregivers": concurrent_caregivers,
        "hourly_cost_cents": hourly_cost_cents,
        "coverage_hours": coverage_hours,
        "base_cost_cents": costs["base_cost_cents"],
        "coordination_fee_cents": costs["coordination_fee_cents"],
        "total_projected_cost_cents": costs["total_projected_cost_cents"],
        "auth_status": "PROPOSED",
        "coi_status": coi_status,
        "disclosure_text": disclosure_text,
        "suspension_reason": "NONE",
        "termination_reason": "NONE",
    })
    db.authorizations[record["id"]] = record
    touch(plan)
    touch(client)
    return envelope.created(serialize.authorization(record))


@bp.route("/care/service-authorizations", methods=["GET"])
def list_authorizations():
    actor = auth.actor_for(*auth.ALL_ROLES)
    limit, offset = v.paging()
    scope = auth.family_scope_client(actor)
    records = list(db.authorizations.values())
    if scope is not None:
        records = [r for r in records if r["client_id"] == scope]
    records = lookup.filter_records(records, FILTERS, v.filters(FILTERS.keys()))
    records = ordered(records)
    return envelope.page([serialize.authorization(r) for r in records],
                         limit, offset)


@bp.route("/care/service-authorizations/<authorization_id>", methods=["GET"])
def read_authorization(authorization_id):
    actor = auth.actor_for(*auth.ALL_ROLES)
    record = lookup.need_authorization(authorization_id)
    auth.family_read_guard(actor, record["client_id"])
    return envelope.ok(serialize.authorization(record))


@bp.route("/care/service-authorizations/<authorization_id>/state",
          methods=["PATCH"])
def authorization_state(authorization_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_SUPERVISOR)
    body = v.json_body()
    auth.owns_target(actor, OWNERSHIP, v.raw_field(body, "to_state"))
    to_state = v.req_enum(body, "to_state", AUTH_STATUSES)
    v.opt_str(body, "reason")
    record = lookup.need_authorization(authorization_id)
    auth.resolve_supervisor(actor)
    plan = db.care_plans[record["care_plan_id"]]
    client = db.clients[record["client_id"]]
    vendor = db.vendors[record["vendor_id"]]
    if to_state == "AUTHORIZED":
        _authorize(record, plan, client, vendor)
    elif to_state == "ACTIVE":
        _activate(record, client, vendor)
    elif to_state == "SUSPENDED":
        if record["auth_status"] != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "Only an ACTIVE authorization may be suspended.")
        derive.suspend_authorization(record, "FAMILY_REQUEST")
    elif to_state == "TERMINATED":
        if record["auth_status"] not in derive.LIVE_AUTH_STATUSES:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "TERMINATED is not reachable from %s."
                           % record["auth_status"])
        derive.terminate_authorization(record, "CARE_MANAGER_REQUEST")
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "%s may not be requested." % to_state)
    return envelope.ok(serialize.authorization(record))


def _authorize(record, plan, client, vendor):
    """The most heavily guarded transition in the system; order is pinned."""
    if record["auth_status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "AUTHORIZED is only reachable from PROPOSED.")
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_CARE_PLAN_NOT_ACTIVE",
                       "The parent care plan is no longer ACTIVE.")
    if client["status"] in ("SUSPENDED_NONPAYMENT", "DISCHARGED"):
        raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                       "The client is not in service.")
    if vendor["standing"] == "BARRED":
        raise ApiError("ERR_VENDOR_BARRED", "The vendor is barred.")
    if record["coi_status"] not in ("NOT_REQUIRED", "ACKNOWLEDGED"):
        raise ApiError("ERR_COI_NOT_ACKNOWLEDGED",
                       "The conflict-of-interest disclosure is outstanding.")
    if not derive.coverage_capacity_holds(client, record):
        raise ApiError("ERR_COVERAGE_CAPACITY_EXCEEDED",
                       "Aggregate concurrent-caregiver capacity would be "
                       "exceeded across the coverage window.")
    if derive.retainer_balance(client["id"]) < client["retainer_floor_cents"]:
        raise ApiError("ERR_RETAINER_INSUFFICIENT",
                       "The client's retainer balance is below the floor.")
    record["auth_status"] = "AUTHORIZED"
    touch(record)
    touch(plan)
    touch(client)


def _activate(record, client, vendor):
    if record["auth_status"] == "AUTHORIZED":
        if client["status"] != "ACTIVE_CARE":
            raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                           "The client is not in active care.")
        if not derive.coverage_capacity_holds(client, record):
            raise ApiError("ERR_COVERAGE_CAPACITY_EXCEEDED",
                           "Aggregate concurrent-caregiver capacity would be "
                           "exceeded across the coverage window.")
        record["auth_status"] = "ACTIVE"
        touch(record)
    elif record["auth_status"] == "SUSPENDED":
        if vendor["standing"] == "BARRED":
            raise ApiError("ERR_VENDOR_BARRED", "The vendor is barred.")
        if client["status"] != "ACTIVE_CARE":
            raise ApiError("ERR_CLIENT_NOT_IN_SERVICE",
                           "The client is not in active care.")
        if not derive.coverage_capacity_holds(client, record):
            raise ApiError("ERR_COVERAGE_CAPACITY_EXCEEDED",
                           "Aggregate concurrent-caregiver capacity would be "
                           "exceeded across the coverage window.")
        derive.reactivate_authorization(record)
    else:
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "ACTIVE is not reachable from %s."
                       % record["auth_status"])


@bp.route("/care/service-authorizations/<authorization_id>/coi-events",
          methods=["POST"])
def coi_event(authorization_id):
    actor = auth.actor_for(auth.ROLE_CARE_MANAGER, auth.ROLE_FAMILY)
    body = v.json_body()
    auth.owns_target(actor, COI_OWNERSHIP, v.raw_field(body, "action"))
    action = v.req_enum(body, "action", COI_ACTIONS)
    v.opt_str(body, "note")
    contact = None
    if action == "ACKNOWLEDGE":
        contact_id = v.req_str(body, "acknowledged_by_contact_id", 1, None)
        contact = lookup.need_contact(contact_id)
    record = lookup.need_authorization(authorization_id)
    client = db.clients[record["client_id"]]
    if action == "DISCLOSE":
        if record["coi_status"] != "PENDING_DISCLOSURE":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "DISCLOSED is only reachable from "
                           "PENDING_DISCLOSURE.")
        if record["auth_status"] == "TERMINATED":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "A terminated authorization carries no live "
                           "disclosure obligation.")
        record["coi_status"] = "DISCLOSED"
        touch(record)
        return envelope.ok(serialize.authorization(record))
    if actor.user_id != contact["id"]:
        raise ApiError("ERR_UNAUTHORIZED",
                       "Nobody may acknowledge a disclosure on somebody else's "
                       "behalf.")
    if record["coi_status"] != "DISCLOSED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "ACKNOWLEDGED is only reachable from DISCLOSED.")
    if contact["client_id"] != record["client_id"] or \
            not contact["is_surrogate_decision_maker"] or \
            contact["contact_role"] not in ELIGIBLE_ACK_ROLES:
        raise ApiError("ERR_COI_ACK_BY_INELIGIBLE_PARTY",
                       "This contact holds no authority to acknowledge the "
                       "disclosure.")
    record["coi_status"] = "ACKNOWLEDGED"
    record["coi_acknowledged_by_contact_id"] = contact["id"]
    touch(record)
    touch(client)
    return envelope.ok(serialize.authorization(record))
