"""Simulation deliveries, the interaction-event machine and interventions."""
from flask import Blueprint

import calc
import cascades
import derive
import guards
import lookups
from envelope import created, ok, ok_list, paginate
from errors import fail
from store import new_row, now, ordered, store, touch

bp = Blueprint("simulations", __name__)

INTERACTABLE = ("DELIVERED", "REPORTED", "CLICKED")


# ------------------------------------------------------------------ deliveries
@bp.get("/awareness/simulation-deliveries/<delivery_id>")
def read_delivery(delivery_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    return ok(derive.delivery_json(lookups.get_delivery(delivery_id)))


@bp.get("/awareness/simulation-deliveries")
def list_deliveries():
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    limit, offset = guards.pagination()
    campaign_id = guards.query_str("campaign_id")
    employee_id = guards.query_str("employee_id")
    state = guards.query_enum("state", calc.DELIVERY_STATES)
    outcome = guards.query_enum("outcome_class", calc.OUTCOME_CLASSES)

    rows = []
    for row in ordered(list(store.deliveries.values())):
        if campaign_id is not None and row["campaign_id"] != campaign_id:
            continue
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if state is not None and row["state"] != state:
            continue
        if outcome is not None and calc.outcome_class(row) != outcome:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.delivery_json(r) for r in page], limit, offset, total)


# ----------------------------------------------------------- interaction events
def _apply_report(delivery, occurred_at):
    if delivery["state"] == "DELIVERED":
        delivery["state"] = "REPORTED"
        delivery["first_report_at"] = occurred_at
        touch(delivery)
        return "DELIVERED->REPORTED", False
    if delivery["state"] == "CLICKED":
        # The CLICKED -> CLICKED self-loop: the state does not move.
        if delivery["first_report_at"] is None:
            delivery["first_report_at"] = occurred_at
        touch(delivery)
        return "NONE", False
    # A duplicate REPORT on a REPORTED delivery changes nothing at all.
    return "NONE", False


def _apply_click(delivery, occurred_at):
    previous = delivery["state"]
    if previous not in ("DELIVERED", "REPORTED"):
        return "NONE", False               # duplicate CLICK on a CLICKED delivery
    delivery["state"] = "CLICKED"
    delivery["first_click_at"] = occurred_at
    touch(delivery)
    return "%s->CLICKED" % previous, True


def _apply_credential(delivery, occurred_at):
    delivery["state"] = "CREDENTIAL_SUBMITTED"
    delivery["credential_submitted_at"] = occurred_at
    touch(delivery)
    return "CLICKED->CREDENTIAL_SUBMITTED", True


@bp.post("/awareness/simulation-deliveries/<delivery_id>/interactions")
def append_interaction(delivery_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    event_type = guards.req_enum(data, "event_type", calc.EVENT_TYPES)
    occurred_at = guards.req_instant(data, "occurred_at")
    source = guards.req_enum(data, "source", calc.EVENT_SOURCES)

    delivery = lookups.get_delivery(delivery_id)
    if delivery["state"] not in INTERACTABLE:
        fail("ERR_DELIVERY_NOT_INTERACTABLE",
             "a delivery in state %s accepts no interaction" % delivery["state"])
    campaign = store.campaigns.get(delivery["campaign_id"])
    if campaign is None or campaign["state"] != "RUNNING":
        fail("ERR_CAMPAIGN_STATE_INVALID", "the owning campaign is not RUNNING")

    if event_type == "CREDENTIAL_SUBMIT":
        template = store.templates.get(campaign["template_id"])
        if template is None or not template["credential_capture_enabled"]:
            fail("ERR_CREDENTIAL_CAPTURE_DISABLED",
                 "the campaign's template does not enable credential capture")
        if delivery["first_click_at"] is None:
            fail("ERR_CREDENTIAL_WITHOUT_CLICK", "no prior CLICK exists on this delivery")

    clock = now()
    if delivery["delivered_at"] is not None and occurred_at < delivery["delivered_at"]:
        fail("ERR_EVENT_OUT_OF_ORDER", "occurred_at precedes the delivery instant")
    if occurred_at > clock:
        fail("ERR_EVENT_OUT_OF_ORDER", "occurred_at is later than the logical clock")
    if event_type == "CREDENTIAL_SUBMIT" and occurred_at < delivery["first_click_at"]:
        fail("ERR_EVENT_OUT_OF_ORDER", "occurred_at precedes the first click")

    sequence_index = len(calc.events_of_delivery(delivery["id"])) + 1
    if event_type == "OPEN":
        effect, failure = "NONE", False
    elif event_type == "REPORT":
        effect, failure = _apply_report(delivery, occurred_at)
    elif event_type == "CLICK":
        effect, failure = _apply_click(delivery, occurred_at)
    else:
        effect, failure = _apply_credential(delivery, occurred_at)

    event = new_row(False)
    event.update({
        "delivery_id": delivery["id"],
        "event_type": event_type,
        "occurred_at": occurred_at,
        "source": source,
        "sequence_index": sequence_index,
        "superseding_effect": effect,
    })
    store.events[event["id"]] = event

    if failure:
        emp = cascades.employee_of(delivery)
        if emp is not None:
            # repeat_clicker_tier, consecutive_clean_simulations and the risk
            # scores are all derived, so the intervention cascade is the only
            # write the failure needs beyond the employee version bump.
            cascades.evaluate_intervention(emp, delivery)
            cascades.bump_employee(emp)
    return created(derive.event_json(event))


@bp.get("/awareness/simulation-deliveries/<delivery_id>/interaction-events")
def list_interaction_events(delivery_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    limit, offset = guards.pagination()
    delivery = lookups.get_delivery(delivery_id)
    rows = calc.events_of_delivery(delivery["id"])
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.event_json(r) for r in page], limit, offset, total)


# --------------------------------------------------------------- interventions
@bp.get("/awareness/interventions/<intervention_id>")
def read_intervention(intervention_id):
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    return ok(derive.intervention_json(lookups.get_intervention(intervention_id)))


@bp.get("/awareness/interventions")
def list_interventions():
    guards.authorize("ProgramAdmin", "SecurityAnalyst")
    limit, offset = guards.pagination()
    employee_id = guards.query_str("employee_id")
    delivery_id = guards.query_str("triggering_delivery_id")
    coaching_id = guards.query_str("coaching_assignment_id")
    state = guards.query_enum("state", calc.INTERVENTION_STATES)

    rows = []
    for row in ordered(list(store.interventions.values())):
        if employee_id is not None and row["employee_id"] != employee_id:
            continue
        if delivery_id is not None and row["triggering_delivery_id"] != delivery_id:
            continue
        if coaching_id is not None and row["coaching_assignment_id"] != coaching_id:
            continue
        if state is not None and row["state"] != state:
            continue
        rows.append(row)
    page, total = paginate(rows, limit, offset)
    return ok_list([derive.intervention_json(r) for r in page], limit, offset, total)


@bp.post("/awareness/interventions/<intervention_id>/assign-coaching")
def assign_coaching(intervention_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    module_id = guards.req_str(data, "module_id")

    iv = lookups.get_intervention(intervention_id)
    module = lookups.get_module(module_id)
    if iv["state"] not in ("OPEN", "ESCALATED_TO_MANAGER"):
        fail("ERR_INTERVENTION_STATE_INVALID",
             "cannot assign coaching from state %s" % iv["state"])
    if module["status"] != "PUBLISHED":
        fail("ERR_MODULE_NOT_PUBLISHED", "the coaching module is not PUBLISHED")
    if module["module_type"] != "REMEDIAL":
        fail("ERR_COACHING_MODULE_TYPE_INVALID", "a coaching module must be REMEDIAL")

    emp = store.employees.get(iv["employee_id"])
    if emp is None:
        fail("ERR_EMPLOYEE_NOT_FOUND", "the intervention's employee no longer exists")
    assignment = cascades.create_assignment(emp, module, "REMEDIAL")
    iv["coaching_assignment_id"] = assignment["id"]
    iv["state"] = "COACHING_ASSIGNED"
    touch(iv)
    cascades.bump_employee(emp)
    return ok(derive.intervention_json(iv))


@bp.post("/awareness/interventions/<intervention_id>/close")
def close_intervention(intervention_id):
    guards.authorize("ProgramAdmin")
    data = guards.body()
    resolution_code = guards.req_str(data, "resolution_code")

    iv = lookups.get_intervention(intervention_id)
    if iv["state"] != "COACHING_COMPLETED":
        fail("ERR_INTERVENTION_STATE_INVALID", "cannot close from state %s" % iv["state"])

    emp = store.employees.get(iv["employee_id"])
    iv["state"] = "CLOSED_RESOLVED"
    iv["closed_at"] = now()
    iv["resolution_code"] = resolution_code
    if emp is not None and calc.consecutive_clean_simulations(emp["id"]) >= calc.CLEAN_STREAK_FOR_DECAY:
        # The only place a tier ever decays -- a demonstrated clean streak earns it.
        emp["_tier_decay_total"] = emp.get("_tier_decay_total", 0) + 1
        iv["tier_decay_applied"] = True
    touch(iv)
    cascades.bump_employee(emp)
    return ok(derive.intervention_json(iv))
