"""Clock, clients, projects, phases, labor rates and billing multipliers."""
from decimal import Decimal

from flask import Blueprint

import calc
import guards
import response as resp
import serialize as ser
import validate as V
from auth import authenticate, check_project_manager
from db import db, new_id
from errors import ApiError
from money import ZERO2, ZERO4, q2, q4

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# The logical clock (PRD 2.6)
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["FirmAdmin"])
    body = V.body_json()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        raise V.bad("Field 'to_iso8601' is required.")
    db.clock = V.parse_instant("to_iso8601", body["to_iso8601"])
    return resp.ok({})


# ---------------------------------------------------------------------------
# Clients (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/clients", methods=["POST"])
def create_client():
    authenticate(["FirmAdmin", "Controller"])
    body = V.body_json()
    row = {
        "id": new_id(),
        "name": V.req_string(body, "name"),
        "is_public_agency": V.req_bool(body, "is_public_agency"),
        "retainage_pct": V.req_ratio(body, "retainage_pct",
                                     minimum=Decimal("0.0000"), maximum=Decimal("0.2000")),
        "expense_markup_pct": V.req_ratio(body, "expense_markup_pct",
                                          minimum=Decimal("0.0000"), maximum=Decimal("0.2500")),
        "disallowed_categories": V.req_string_list(body, "disallowed_categories",
                                                   V.EXPENSE_CATEGORIES),
        "receipt_required_above": V.req_money(body, "receipt_required_above",
                                              minimum=ZERO2),
        "review_cycle_days": V.req_int(body, "review_cycle_days", minimum=1, maximum=90),
    }
    calc.stamp_new(row, mutable=False)
    db.clients[row["id"]] = row
    return resp.created(ser.client_out(row))


@bp.route("/clients/<client_id>", methods=["GET"])
def get_client(client_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.clients, client_id, "ERR_CLIENT_NOT_FOUND", "Client")
    return resp.ok(ser.client_out(row))


@bp.route("/clients", methods=["GET"])
def list_clients():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    is_public = V.query_bool("is_public_agency")
    rows = list(db.clients.values())
    if is_public is not None:
        rows = [c for c in rows if c["is_public_agency"] == is_public]
    return resp.paged(rows, ser.client_out)


# ---------------------------------------------------------------------------
# Projects (PRD 3.1)
# ---------------------------------------------------------------------------
@bp.route("/projects", methods=["POST"])
def create_project():
    authenticate(["FirmAdmin", "Controller"])
    body = V.body_json()
    client_id = V.req_string(body, "client_id")
    name = V.req_string(body, "name")
    contract_type = V.req_enum(body, "contract_type", V.CONTRACT_TYPES)
    contract_amount = V.req_money(body, "contract_amount", min_exclusive=ZERO2)
    pm_user_id = V.req_string(body, "project_manager_user_id")
    method = V.req_enum(body, "percent_complete_method", V.PERCENT_COMPLETE_METHODS)
    target_multiplier = V.req_ratio(body, "target_multiplier",
                                    minimum=Decimal("1.0000"), maximum=Decimal("6.0000"))
    wip_threshold = V.opt_money(body, "wip_alert_threshold", minimum=ZERO2,
                                default=calc.DEFAULT_WIP_ALERT_THRESHOLD)
    guards.reference(db.clients, client_id, "Client")
    row = {
        "id": new_id(),
        "client_id": client_id,
        "name": name,
        "contract_type": contract_type,
        "contract_amount": q2(contract_amount),
        "project_manager_user_id": pm_user_id,
        "percent_complete_method": method,
        "target_multiplier": q4(target_multiplier),
        "wip_alert_threshold": q2(wip_threshold),
        "status": "SETUP",
        "locked_through_date": None,
        "overhead_adjustment_required": False,
    }
    calc.stamp_new(row)
    db.projects[row["id"]] = row
    return resp.created(ser.project_out(row))


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND", "Project")
    return resp.ok(ser.project_out(row))


@bp.route("/projects", methods=["GET"])
def list_projects():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    client_id = V.query_str("client_id")
    pm_user_id = V.query_str("project_manager_user_id")
    status = V.query_enum("status", V.PROJECT_STATUSES)
    rows = list(db.projects.values())
    if client_id is not None:
        rows = [p for p in rows if p["client_id"] == client_id]
    if pm_user_id is not None:
        rows = [p for p in rows if p["project_manager_user_id"] == pm_user_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return resp.paged(rows, ser.project_out)


@bp.route("/projects/<project_id>/activate", methods=["POST"])
def activate_project(project_id):
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager"])
    check_project_manager(role, user_id, guards.maybe(db.projects, project_id))
    project = guards.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND", "Project")
    # PRD 3.1: activation requires SETUP, at least one phase, and at least one
    # ACTIVE billing multiplier. No dedicated error id is declared for the two
    # structural preconditions, so the declared-transition rung reports them.
    if project["status"] != "SETUP":
        raise guards.invalid_state("A project may only be activated from SETUP.")
    if not calc.project_phases(project["id"]):
        raise guards.invalid_state("A project needs at least one phase before activation.")
    actives = [m for m in db.billing_multipliers.values()
               if m["project_id"] == project["id"] and m["status"] == "ACTIVE"]
    if not actives:
        raise guards.invalid_state(
            "A project needs at least one ACTIVE billing multiplier before activation.")
    project["status"] = "ACTIVE"
    calc.touch(project)
    return resp.ok(ser.project_out(project))


@bp.route("/projects/<project_id>/lock-period", methods=["POST"])
def lock_period(project_id):
    authenticate(["Controller"])
    body = V.body_json()
    locked_through = V.req_date(body, "locked_through_date")
    project = guards.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND", "Project")
    project["locked_through_date"] = locked_through
    calc.touch(project)
    return resp.ok(ser.project_out(project))


@bp.route("/projects/<project_id>/wip-aging", methods=["GET"])
def wip_aging(project_id):
    authenticate(["Controller", "ProjectManager", "ProjectAccountant"])
    project = guards.lookup(db.projects, project_id, "ERR_PROJECT_NOT_FOUND", "Project")
    return resp.ok(ser.wip_aging_report(project))


# ---------------------------------------------------------------------------
# Phases -- the work breakdown structure (PRD 3.1, 3.6)
# ---------------------------------------------------------------------------
@bp.route("/phases", methods=["POST"])
def create_phase():
    user_id, role = authenticate(["FirmAdmin", "Controller", "ProjectManager"])
    peek = V.peek_body()
    check_project_manager(role, user_id, guards.maybe(db.projects, peek.get("project_id")))
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    wbs_code = V.req_string(body, "wbs_code")
    fee_basis = V.req_enum(body, "fee_basis", V.FEE_BASES)
    parent_phase_id = V.opt_string(body, "parent_phase_id", allow_empty=False)
    budget_labor_cost = V.req_money(body, "budget_labor_cost", minimum=ZERO2)
    consultant_budget = V.req_money(body, "consultant_budget", minimum=ZERO2)
    # PRD 3.1/2.5: "Supplying the fee field that contradicts the declared basis,
    # or omitting the one it requires, is a malformed request."
    if fee_basis == "PERCENT_OF_CONTRACT":
        V.forbid(body, "lump_sum_fee",
                 "lump_sum_fee must be omitted when fee_basis is PERCENT_OF_CONTRACT.")
        fee_percent = V.req_ratio(body, "fee_percent", minimum=Decimal("0.0001"),
                                  maximum=Decimal("1.0000"))
        lump_sum_fee = None
    else:
        V.forbid(body, "fee_percent", "fee_percent must be omitted when fee_basis is LUMP_SUM.")
        lump_sum_fee = V.req_money(body, "lump_sum_fee", min_exclusive=ZERO2)
        fee_percent = None

    project = guards.reference(db.projects, project_id, "Project")
    parent = None
    if parent_phase_id is not None:
        parent = guards.reference(db.phases, parent_phase_id, "Parent phase")
        # PRD 3.1: "A supplied parent_phase_id must reference a phase of the same
        # project and must not close a cycle in the tree; either fault is ERR_WBS_CYCLE."
        if parent["project_id"] != project_id:
            raise ApiError("ERR_WBS_CYCLE",
                           "The parent phase belongs to a different project.")
    for existing in calc.project_phases(project_id):
        if existing["wbs_code"] == wbs_code:
            raise ApiError("ERR_WBS_CODE_DUPLICATE",
                           "wbs_code '%s' is already used on this project." % wbs_code)

    if fee_basis == "PERCENT_OF_CONTRACT":
        phase_fee = q2(project["contract_amount"] * fee_percent)
        fee_percent = q4(fee_percent)
    else:
        phase_fee = q2(lump_sum_fee)
        lump_sum_fee = q2(lump_sum_fee)

    if parent is not None:
        # PRD 3.1: the sum of the children's phase_fee may not exceed the parent's.
        sibling_total = ZERO2
        for sibling in db.phases.values():
            if sibling.get("parent_phase_id") == parent["id"]:
                sibling_total += sibling["phase_fee"]
        if q2(sibling_total + phase_fee) > parent["phase_fee"]:
            raise ApiError("ERR_WBS_FEE_ROLLUP_MISMATCH",
                           "The children's fees would exceed the parent phase fee.")

    row = {
        "id": new_id(),
        "project_id": project_id,
        "parent_phase_id": parent_phase_id,
        "wbs_code": wbs_code,
        "fee_basis": fee_basis,
        "fee_percent": fee_percent,
        "lump_sum_fee": lump_sum_fee,
        "phase_fee": phase_fee,
        "budget_labor_cost": q2(budget_labor_cost),
        "consultant_budget": q2(consultant_budget),
        "status": "PLANNED",
        "assessed_percent_complete": ZERO4,
    }
    calc.stamp_new(row)
    db.phases[row["id"]] = row
    return resp.created(ser.phase_out(row))


@bp.route("/phases/<phase_id>", methods=["GET"])
def get_phase(phase_id):
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    row = guards.lookup(db.phases, phase_id, "ERR_PHASE_NOT_FOUND", "Phase")
    return resp.ok(ser.phase_out(row))


@bp.route("/phases", methods=["GET"])
def list_phases():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    parent_phase_id = V.query_str("parent_phase_id")
    status = V.query_enum("status", V.PHASE_STATUSES)
    rows = list(db.phases.values())
    if project_id is not None:
        rows = [p for p in rows if p["project_id"] == project_id]
    if parent_phase_id is not None:
        rows = [p for p in rows if p["parent_phase_id"] == parent_phase_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    return resp.paged(rows, ser.phase_out)


@bp.route("/phases/<phase_id>/assess", methods=["POST"])
def assess_phase(phase_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    phase = guards.maybe(db.phases, phase_id)
    check_project_manager(role, user_id,
                          calc.project_of_phase(phase) if phase is not None else None)
    body = V.body_json()
    assessed = V.req_ratio(body, "assessed_percent_complete", minimum=ZERO4,
                           maximum=Decimal("1.0000"))
    phase = guards.lookup(db.phases, phase_id, "ERR_PHASE_NOT_FOUND", "Phase")
    project = calc.project_of_phase(phase)
    guards.require_active_project(project)
    if phase["status"] not in ("PLANNED", "IN_PROGRESS"):
        raise guards.invalid_state("A COMPLETE phase can no longer be assessed.")
    phase["assessed_percent_complete"] = q4(assessed)
    calc.touch(phase)
    return resp.ok(ser.phase_out(phase))


@bp.route("/phases/<phase_id>/complete", methods=["POST"])
def complete_phase(phase_id):
    user_id, role = authenticate(["ProjectManager", "Controller"])
    phase = guards.maybe(db.phases, phase_id)
    check_project_manager(role, user_id,
                          calc.project_of_phase(phase) if phase is not None else None)
    phase = guards.lookup(db.phases, phase_id, "ERR_PHASE_NOT_FOUND", "Phase")
    project = calc.project_of_phase(phase)
    guards.require_active_project(project)
    if phase["status"] != "IN_PROGRESS":
        raise guards.invalid_state("A phase may only be completed from IN_PROGRESS.")
    # PRD 3.6: no time entry in SUBMITTED, no expense in PENDING_REVIEW and no
    # EXECUTED subcontract whose released_to_date is below its committed_amount.
    for entry in calc.phase_time_entries(phase["id"]):
        if entry["status"] == "SUBMITTED":
            raise ApiError("ERR_PHASE_HAS_OPEN_CHARGES",
                           "A time entry on this phase is still SUBMITTED.")
    for expense in calc.phase_expenses(phase["id"]):
        if expense["allowability_status"] == "PENDING_REVIEW":
            raise ApiError("ERR_PHASE_HAS_OPEN_CHARGES",
                           "An expense on this phase is still PENDING_REVIEW.")
    for sub in calc.phase_subcontracts(phase["id"]):
        if sub["status"] == "EXECUTED" and \
                calc.subcontract_released_to_date(sub) < sub["committed_amount"]:
            raise ApiError("ERR_PHASE_HAS_OPEN_CHARGES",
                           "An executed subcontract on this phase still has an open commitment.")
    phase["status"] = "COMPLETE"
    calc.touch(phase)
    calc.touch(project)
    calc.maybe_close_project(project)
    return resp.ok(ser.phase_out(phase))


@bp.route("/phases/<phase_id>/earned-value", methods=["GET"])
def phase_earned_value(phase_id):
    authenticate(["Controller", "ProjectManager", "ProjectAccountant"])
    phase = guards.lookup(db.phases, phase_id, "ERR_PHASE_NOT_FOUND", "Phase")
    return resp.ok(ser.earned_value_report(phase))


# ---------------------------------------------------------------------------
# Labour cost rates -- append-only, overlap rejected (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/labor-rates", methods=["POST"])
def create_labor_rate():
    authenticate(["Controller"])
    body = V.body_json()
    role_code = V.req_enum(body, "role_code", V.ROLE_CODES)
    raw_cost_rate = V.req_money(body, "raw_cost_rate", min_exclusive=ZERO2)
    effective_from = V.req_date(body, "effective_from")
    effective_to = V.opt_date(body, "effective_to")
    # PRD 3.2: effective_to, "when supplied, must be strictly later than effective_from".
    if effective_to is not None and effective_to <= effective_from:
        raise V.bad("effective_to must be strictly later than effective_from.")
    for other in db.labor_rates.values():
        if other["role_code"] != role_code:
            continue
        if calc.labor_rate_windows_overlap(effective_from, effective_to,
                                           other["effective_from"], other["effective_to"]):
            raise ApiError("ERR_RATE_PERIOD_OVERLAP",
                           "Another rate for %s already covers part of this window." % role_code)
    row = {
        "id": new_id(),
        "role_code": role_code,
        "raw_cost_rate": q2(raw_cost_rate),
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    calc.stamp_new(row, mutable=False)
    db.labor_rates[row["id"]] = row
    return resp.created(ser.labor_rate_out(row))


@bp.route("/labor-rates", methods=["GET"])
def list_labor_rates():
    authenticate(["FirmAdmin", "Controller", "ProjectAccountant"])
    role_code = V.query_enum("role_code", V.ROLE_CODES)
    raw_on = V.query_str("effective_on")
    effective_on = V.parse_date_str("effective_on", raw_on) if raw_on is not None else None
    rows = list(db.labor_rates.values())
    if role_code is not None:
        rows = [x for x in rows if x["role_code"] == role_code]
    if effective_on is not None:
        # PRD 2.9: "effective_on resolves the window covering a given date."
        rows = [x for x in rows if calc._covers(x, effective_on)]
    return resp.paged(rows, ser.labor_rate_out)


# ---------------------------------------------------------------------------
# Billing multipliers -- truncate on supersede (PRD 3.2)
# ---------------------------------------------------------------------------
@bp.route("/billing-multipliers", methods=["POST"])
def create_billing_multiplier():
    authenticate(["Controller"])
    body = V.body_json()
    project_id = V.req_string(body, "project_id")
    multiplier = V.req_ratio(body, "multiplier", minimum=Decimal("1.0000"),
                             maximum=Decimal("6.0000"))
    effective_from = V.req_date(body, "effective_from")
    effective_to = V.opt_date(body, "effective_to")
    expected_version = V.req_int(body, "expected_project_version")
    project = guards.reference(db.projects, project_id, "Project")
    guards.require_project_version(project, expected_version)
    # PRD 3.1: for multiplier creation the only status that triggers
    # ERR_PROJECT_NOT_ACTIVE is CLOSED.
    guards.require_project_not_closed(project)

    multiplier = q4(multiplier)
    ceiling = calc.project_certified_multiplier_ceiling(project)
    if ceiling is not None and multiplier > ceiling:
        raise ApiError("ERR_MULTIPLIER_ABOVE_CERTIFIED_CEILING",
                       "The multiplier exceeds the certified ceiling of %s." % ceiling)

    incumbent = None
    for existing in db.billing_multipliers.values():
        if existing["project_id"] == project_id and existing["status"] == "ACTIVE":
            incumbent = existing
            break
    # PRD 3.2: the successor's effective_from must be strictly later than the
    # incumbent's, and it must not fall earlier than the work_date of any charge
    # that has already been billed.
    if incumbent is not None and effective_from <= incumbent["effective_from"]:
        raise ApiError("ERR_MULTIPLIER_BACKDATED",
                       "effective_from must be strictly later than the incumbent multiplier's.")
    for entry in calc.project_time_entries(project_id):
        if entry["status"] == "BILLED" and entry["work_date"] > effective_from:
            raise ApiError("ERR_MULTIPLIER_BACKDATED",
                           "A billed charge already exists after the supplied effective_from.")

    if incumbent is not None:
        incumbent["effective_to"] = effective_from
        incumbent["status"] = "SUPERSEDED"
        calc.touch(incumbent)

    row = {
        "id": new_id(),
        "project_id": project_id,
        "multiplier": multiplier,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "status": "ACTIVE",
    }
    calc.stamp_new(row)
    db.billing_multipliers[row["id"]] = row
    calc.touch(project)
    return resp.created(ser.billing_multiplier_out(row))


@bp.route("/billing-multipliers/<billing_multiplier_id>", methods=["GET"])
def get_billing_multiplier(billing_multiplier_id):
    authenticate(["FirmAdmin", "Controller", "ProjectAccountant"])
    row = guards.lookup(db.billing_multipliers, billing_multiplier_id,
                        "ERR_MULTIPLIER_NOT_FOUND", "Billing multiplier")
    return resp.ok(ser.billing_multiplier_out(row))


@bp.route("/billing-multipliers", methods=["GET"])
def list_billing_multipliers():
    authenticate(["FirmAdmin", "Controller", "ProjectManager", "ProjectAccountant"])
    project_id = V.query_str("project_id")
    status = V.query_enum("status", V.MULTIPLIER_STATUSES)
    rows = list(db.billing_multipliers.values())
    if project_id is not None:
        rows = [x for x in rows if x["project_id"] == project_id]
    if status is not None:
        rows = [x for x in rows if x["status"] == status]
    return resp.paged(rows, ser.billing_multiplier_out)
