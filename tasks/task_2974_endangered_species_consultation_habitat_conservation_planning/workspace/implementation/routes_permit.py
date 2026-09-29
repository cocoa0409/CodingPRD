"""Permit issuance, take monitoring, adjudication and circumstance events."""
from decimal import Decimal

from flask import Blueprint

import auth
import calc
import cascades
import envelope
import resolve
import serialize
import shape
import store
import util
from errors import ApiError

bp = Blueprint("permits", __name__)

PROPONENT = ("Proponent",)
AGENCY = ("WildlifeAgency",)


def _seed_take_ledger(action):
    """Inherited, not recomputed: the opinion of the action's active
    consultation wins, with the greatest issued_at and the earlier created_at
    breaking the tie."""
    consultation_id = action.get("active_consultation_id") if action else None
    opinions = []
    if consultation_id is not None:
        opinions = store.where("opinions", consultation_id=consultation_id)
    if opinions:
        best = sorted(
            opinions, key=lambda o: (o["issued_at"], -o["_seq"]), reverse=True
        )[0]
        return (
            best["authorized_take_units"],
            best["take_unit"],
            best["reinitiation_trigger_units"],
        )
    take = calc.incidental_take(action) if action is not None else None
    if take is None:
        return util.q2(0), "ACRES", util.q2(0)
    return (
        take["authorized_take_units"],
        take["take_unit"],
        take["reinitiation_trigger_units"],
    )


@bp.route("/habitat-conservation-plans/<hid>/incidental-take-permits",
          methods=["POST"])
def issue_permit(hid):
    caller = auth.authenticate(AGENCY)
    plan = resolve.plan(hid)

    body = shape.Body()
    term_start = body.date("term_start")
    reference = body.string("implementing_agreement_reference", 6, 64)
    body.close()

    if plan["plan_status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    if store.where("permits", hcp_id=plan["id"]):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 11.
    if plan["approved_by_user_id"] is not None and (
        caller.user_id == plan["approved_by_user_id"]
    ):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    action = store.get("actions", plan["project_action_id"])
    authorized, take_unit, trigger = _seed_take_ledger(action)

    row = store.new_row(
        hcp_id=plan["id"],
        permit_number=calc.permit_number(),
        status="ACTIVE",
        term_start=term_start,
        term_end=util.add_years_clamped(term_start, plan["permit_term_years"]),
        implementing_agreement_reference=reference,
        issued_by_user_id=caller.user_id,
        authorized_take_units=authorized,
        take_unit=take_unit,
        reinitiation_trigger_units=trigger,
        take_consumed_units=util.q2(0),
        take_remaining_units=util.q2(authorized),
        suspension_count=0,
    )
    store.insert("permits", row)

    plan["plan_status"] = "IMPLEMENTING"
    store.touch(plan)
    if action is not None and action["status"] == "HCP_DEVELOPMENT":
        action["status"] = "PERMITTED"
        store.touch(action)

    return envelope.created(serialize.permit(row))


@bp.route("/incidental-take-permits/<pid>/monitoring-reports", methods=["POST"])
def submit_report(pid):
    caller = auth.authenticate(PROPONENT)
    permit = resolve.permit(pid)
    auth.require_owner(caller, auth.owner_of_permit(permit))

    body = shape.Body()
    period_start = body.date("period_start")
    period_end = body.date("period_end")
    take_reported = body.quantity("take_units_reported")
    mitigation_verified = body.quantity("mitigation_units_verified")
    expected_version = body.integer("expected_permit_version")
    body.close()

    # Rung 8.
    if expected_version != permit["version"]:
        raise ApiError("ERR_STALE_PERMIT_VERSION")
    # Rung 10 -- the state rule beats the fiscal rule at rung 28.
    if permit["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE")

    # Rung 19 -- the temporal rule beats the overlap rule at rung 21.
    now = store.now()
    if not period_start < period_end:
        raise ApiError("ERR_PERIOD_OUTSIDE_PERMIT_TERM")
    if period_start < permit["term_start"]:
        raise ApiError("ERR_PERIOD_OUTSIDE_PERMIT_TERM")
    if period_end > permit["term_end"]:
        raise ApiError("ERR_PERIOD_OUTSIDE_PERMIT_TERM")
    if util.at_midnight(period_end) > now:
        raise ApiError("ERR_PERIOD_OUTSIDE_PERMIT_TERM")

    # Rung 21 -- half-open and unbuffered; exact adjacency is allowed.
    for other in store.where("reports", permit_id=permit["id"]):
        if other["status"] not in ("SUBMITTED", "ACCEPTED"):
            continue
        if period_start < other["period_end"] and period_end > other["period_start"]:
            raise ApiError("ERR_REPORTING_PERIOD_OVERLAP")

    # Rung 28 -- checked before the ledger is touched at all.
    remaining = util.to_dec(permit["take_remaining_units"])
    if take_reported > remaining:
        raise ApiError("ERR_TAKE_LIMIT_EXCEEDED")

    due_at = util.add_days(period_end, calc.REPORT_DUE_DAYS)
    row = store.new_row(
        permit_id=permit["id"],
        period_start=period_start,
        period_end=period_end,
        take_units_reported=take_reported,
        mitigation_units_verified=mitigation_verified,
        submitted_at=now,
        due_at=due_at,
        is_late=util.date_of(now) > due_at,
        status="SUBMITTED",
        adjudicated_at=None,
        adjudicated_by_user_id=None,
        adjudication_note=None,
    )
    store.insert("reports", row)

    consumed = util.q2(util.to_dec(permit["take_consumed_units"]) + take_reported)
    permit["take_consumed_units"] = consumed
    permit["take_remaining_units"] = util.q2(
        util.to_dec(permit["authorized_take_units"]) - consumed
    )
    store.touch(permit)

    # The threshold check runs after the ledger has moved; equality suspends.
    if consumed >= util.to_dec(permit["reinitiation_trigger_units"]) and (
        permit["status"] == "ACTIVE"
    ):
        cascades.take_exceedance_cascade(permit)

    return envelope.created(serialize.report(row))


@bp.route("/monitoring-reports/<rid>/adjudication", methods=["POST"])
def adjudicate_report(rid):
    caller = auth.authenticate(AGENCY)
    report = resolve.report(rid)

    body = shape.Body()
    decision = body.enum("decision", calc.REPORT_DECISIONS)
    note = body.string("adjudication_note", 1, required=False)
    body.close()

    if report["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    permit = store.get("permits", report["permit_id"])
    # Rung 12.
    if permit is not None and permit["issued_by_user_id"] is not None and (
        caller.user_id == permit["issued_by_user_id"]
    ):
        raise ApiError("ERR_ADJUDICATOR_CONFLICT")

    report["adjudicated_at"] = store.now()
    report["adjudicated_by_user_id"] = caller.user_id
    report["adjudication_note"] = note

    if decision == "ACCEPT":
        report["status"] = "ACCEPTED"
        store.touch(report)
    else:
        report["status"] = "REJECTED"
        store.touch(report)
        if permit is not None:
            consumed = util.q2(
                util.to_dec(permit["take_consumed_units"])
                - util.to_dec(report["take_units_reported"])
            )
            permit["take_consumed_units"] = consumed
            permit["take_remaining_units"] = util.q2(
                util.to_dec(permit["authorized_take_units"]) - consumed
            )
            store.touch(permit)
            trigger = util.to_dec(permit["reinitiation_trigger_units"])
            if consumed < trigger and permit["status"] == "SUSPENDED":
                cascades.unwind_suspension(permit)

    if permit is not None:
        plan = store.get("plans", permit["hcp_id"])
        action = store.get("actions", plan["project_action_id"]) if plan else None
        if action is not None:
            calc.refresh_compliance(calc.proponent_of_action(action))

    return envelope.obj(serialize.report(report))


@bp.route("/habitat-conservation-plans/<hid>/changed-circumstance-events",
          methods=["POST"])
def report_circumstance(hid):
    caller = auth.authenticate(PROPONENT)
    plan = resolve.plan(hid)
    auth.require_owner(caller, auth.owner_of_plan(plan))

    body = shape.Body()
    circumstance_type = body.enum("circumstance_type", calc.CIRCUMSTANCE_TYPES)
    description = body.string("description", 1, 400)
    response_cost = body.money("response_cost_cents", positive=True)
    body.close()

    if plan["plan_status"] not in ("IMPLEMENTING", "SUSPENDED_IMPLEMENTATION"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    if circumstance_type == "CHANGED":
        # Two-bucket waterfall: the plan's own pre-funded reserve, then the
        # permittee.  The permittee bears the whole cost either way.
        draw = min(response_cost, plan["reserve_remaining_cents"])
        required_additional = response_cost - draw
        permittee = response_cost
        agency = 0
        assurances = False
        status = "RESPONSE_REQUIRED" if required_additional > 0 else "RESPONDED"
        plan["reserve_drawn_cents"] = plan["reserve_drawn_cents"] + draw
        calc.refresh_reserve_remaining(plan)
        store.touch(plan)
    else:
        # The reserve is not touched at all; the assurances cap the permittee.
        draw = 0
        required_additional = 0
        cap = util.rhu_int(
            Decimal(plan["endowment_secured_cents"])
            * calc.UNFORESEEN_PERMITTEE_SHARE_PCT
        )
        permittee = min(response_cost, cap)
        agency = response_cost - permittee
        assurances = True
        status = "ASSURANCES_INVOKED"

    row = store.new_row(
        hcp_id=plan["id"],
        circumstance_type=circumstance_type,
        description=description,
        response_cost_cents=response_cost,
        reported_at=store.now(),
        status=status,
        reserve_draw_cents=draw,
        required_additional_cents=required_additional,
        contributed_cents=0,
        permittee_borne_cents=permittee,
        agency_borne_cents=agency,
        assurances_invoked=assurances,
        response_note=None,
    )
    store.insert("events", row)
    return envelope.created(serialize.event(row))


@bp.route("/changed-circumstance-events/<eid>/response", methods=["POST"])
def respond_to_circumstance(eid):
    caller = auth.authenticate(PROPONENT)
    event = resolve.event(eid)
    auth.require_owner(caller, auth.owner_of_event(event))

    body = shape.Body()
    contributed = body.money("contributed_cents")
    note = body.string("response_note", 1, required=False)
    body.close()

    if event["status"] != "RESPONSE_REQUIRED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    # Rung 29.
    if contributed < event["required_additional_cents"]:
        raise ApiError("ERR_RESERVE_CONTRIBUTION_INSUFFICIENT")

    event["status"] = "RESPONDED"
    event["contributed_cents"] = contributed
    event["response_note"] = note
    store.touch(event)

    plan = store.get("plans", event["hcp_id"])
    if plan is not None:
        plan["endowment_secured_cents"] = (
            plan["endowment_secured_cents"] + contributed
        )
        calc.recompute_funding(plan)
        store.touch(plan)
        action = store.get("actions", plan["project_action_id"])
        if action is not None:
            calc.refresh_compliance(calc.proponent_of_action(action))

    return envelope.obj(serialize.event(event))
