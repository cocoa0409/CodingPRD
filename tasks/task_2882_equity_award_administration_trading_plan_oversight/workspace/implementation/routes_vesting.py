"""Vesting, tax allocation, settlement and reversal."""

from flask import Blueprint, request

import auth
import calc
import clock
import envelope
import services
import store
import validate
from auth import AUDITOR, COMPLIANCE, PARTICIPANT, PLAN_ADMIN
from errors import ApiError

bp = Blueprint("vesting", __name__)

EVENT_LIST_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR)
EVENT_ROW_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR, PARTICIPANT)
WITHHOLDING_METHODS = ("SHARE_WITHHOLD", "SELL_TO_COVER", "CASH_REMITTANCE")


@bp.route("/vesting-tranches/<tranche_id>/vest", methods=["POST"])
def vest_tranche(tranche_id):
    actor = auth.begin(PLAN_ADMIN)
    tranche = services.tranche_or_404(tranche_id)
    fmv = validate.field_int(actor.body, "fmv_per_share_cents", minimum=1)
    method = validate.field_enum(
        actor.body, "withholding_method", WITHHOLDING_METHODS,
        required=False, default="SHARE_WITHHOLD")
    if tranche["status"] != "UNVESTED":
        raise ApiError("ERR_TRANCHE_INVALID_STATE")
    grant = store.grants[tranche["grant_id"]]
    if grant["status"] not in ("GRANTED", "PARTIALLY_FORFEITED"):
        raise ApiError("ERR_GRANT_INVALID_STATE")
    plan = services.plan_of_grant(grant)
    services.require_plan_not_terminated(plan)
    if clock.today() < clock.parse_date(tranche["scheduled_vest_date"]):
        raise ApiError("ERR_TRANCHE_INVALID_STATE")
    if tranche["vest_type"] == "PERFORMANCE":
        cycle = store.cycles.get(tranche["performance_cycle_id"])
        if cycle is None or cycle["status"] != "CERTIFIED":
            raise ApiError("ERR_PERFORMANCE_NOT_CERTIFIED")
    tranche["status"] = "VESTED"
    tranche["vested_at"] = clock.fmt_instant(clock.now())
    store.touch(tranche)
    event = services.new_vesting_event(tranche, grant, fmv, method, clock.now())
    return envelope.created(store.public(event))


@bp.route("/vesting-events", methods=["GET"])
def list_events():
    auth.begin(*EVENT_LIST_READERS)
    rows = list(store.events.values())
    for param in ("tranche_id", "tax_status", "settlement_status"):
        value = request.args.get(param)
        if value is not None:
            rows = [r for r in rows if r[param] == value]
    return envelope.page(store.sort_default(rows))


@bp.route("/vesting-events/<event_id>", methods=["GET"])
def read_event(event_id):
    actor = auth.begin(*EVENT_ROW_READERS)
    event = services.event_or_404(event_id)
    auth.scope(actor, services.participant_id_of_event(event))
    return envelope.ok(store.public(event))


@bp.route("/vesting-events/<event_id>/tax-allocations", methods=["GET"])
def list_tax_allocations(event_id):
    actor = auth.begin(*EVENT_ROW_READERS)
    event = services.event_or_404(event_id)
    auth.scope(actor, services.participant_id_of_event(event))
    rows = [r for r in store.tax_allocations.values() if r["vesting_event_id"] == event_id]
    return envelope.page(store.sort_by(rows, "jurisdiction_code"))


@bp.route("/tax-allocations/<allocation_id>", methods=["GET"])
def read_tax_allocation(allocation_id):
    actor = auth.begin(*EVENT_ROW_READERS)
    row = store.tax_allocations.get(allocation_id)
    if row is None:
        raise ApiError("ERR_TAX_ALLOCATION_NOT_FOUND")
    event = store.events[row["vesting_event_id"]]
    auth.scope(actor, services.participant_id_of_event(event))
    return envelope.ok(store.public(row))


@bp.route("/vesting-events/<event_id>/allocate-taxes", methods=["POST"])
def allocate_taxes(event_id):
    auth.begin(PLAN_ADMIN, COMPLIANCE)
    event = services.event_or_404(event_id)
    if event["tax_status"] != "PENDING_ALLOCATION" or event["settlement_status"] != "PENDING_TAX":
        raise ApiError("ERR_VESTING_EVENT_INVALID_STATE")
    tranche = store.tranches[event["tranche_id"]]
    grant = store.grants[tranche["grant_id"]]
    services.require_plan_not_terminated(services.plan_of_grant(grant))
    participant_id = grant["participant_id"]
    period_start = clock.parse_date(event["sourcing_start_date"])
    period_end = clock.parse_date(event["vest_date"])
    rows = [a for a in store.assignments.values() if a["participant_id"] == participant_id]
    contributing = calc.contributing_assignments(rows, period_start, period_end)
    groups = calc.group_by_jurisdiction(contributing)
    allocations, total_workdays = calc.allocate_bps(groups)
    if total_workdays <= 0:
        raise ApiError("ERR_WORKDAY_COVERAGE_GAP")
    total_tax = 0
    for code in sorted(groups.keys()):
        workdays, rate = groups[code]
        allocation_bps = allocations.get(code, 0)
        amount = calc.tax_amount_cents(
            event["taxable_income_cents"], allocation_bps, rate)
        total_tax += amount
        row = store.base_row(versioned=False)
        row.update({
            "vesting_event_id": event["id"],
            "jurisdiction_code": code,
            "workdays_in_period": workdays,
            "allocation_bps": allocation_bps,
            "tax_rate_bps": rate,
            "tax_amount_cents": amount,
        })
        store.tax_allocations[row["id"]] = row
    event["total_workdays"] = total_workdays
    event["total_tax_cents"] = total_tax
    event["blended_rate_bps"] = calc.blended_rate_bps(
        total_tax, event["taxable_income_cents"])
    event["tax_status"] = "ALLOCATED"
    store.touch(event)
    return envelope.ok(store.public(event))


@bp.route("/vesting-events/<event_id>/settle", methods=["POST"])
def settle_event(event_id):
    auth.begin(PLAN_ADMIN)
    event = services.event_or_404(event_id)
    tranche = store.tranches[event["tranche_id"]]
    if event["settlement_status"] != "PENDING_TAX" or tranche["status"] != "VESTED":
        raise ApiError("ERR_VESTING_EVENT_INVALID_STATE")
    grant = store.grants[tranche["grant_id"]]
    services.require_plan_not_terminated(services.plan_of_grant(grant))
    if event["tax_status"] != "ALLOCATED":
        raise ApiError("ERR_TAX_ALLOCATION_MISSING")
    withheld, sold, net, residual, cash_due = calc.withholding(
        event["withholding_method"],
        event["gross_shares"],
        event["fmv_per_share_cents"],
        event["total_tax_cents"],
    )
    event["shares_withheld"] = withheld
    event["shares_sold"] = sold
    event["net_shares_delivered"] = net
    event["residual_cash_cents"] = residual
    event["cash_due_cents"] = cash_due
    event["settlement_status"] = "SETTLED"
    store.touch(event)
    tranche["status"] = "SETTLED"
    store.touch(tranche)
    outstanding = calc.outstanding_shares(services.tranches_of(grant["id"]))
    if outstanding != grant["outstanding_shares"]:
        grant["outstanding_shares"] = outstanding
        store.touch(grant)
    participant = store.participants[grant["participant_id"]]
    shares = event["gross_shares"] if event["withholding_method"] == "CASH_REMITTANCE" \
        else withheld + sold
    services.maybe_create_report(
        participant, "VESTING_SETTLEMENT", event["id"], clock.now(), shares)
    return envelope.ok(store.public(event))


@bp.route("/vesting-events/<event_id>/reverse", methods=["POST"])
def reverse_event(event_id):
    actor = auth.begin(PLAN_ADMIN)
    event = services.event_or_404(event_id)
    reason = validate.field_str(actor.body, "reversal_reason")
    tranche = store.tranches[event["tranche_id"]]
    if event["settlement_status"] != "SETTLED" or tranche["status"] != "SETTLED":
        raise ApiError("ERR_VESTING_EVENT_INVALID_STATE")
    grant = store.grants[tranche["grant_id"]]
    services.require_plan_not_terminated(services.plan_of_grant(grant))
    event["settlement_status"] = "REVERSED"
    event["reversal_reason"] = reason
    event["shares_withheld"] = 0
    event["shares_sold"] = 0
    event["residual_cash_cents"] = 0
    event["cash_due_cents"] = 0
    event["net_shares_delivered"] = event["gross_shares"]
    event["tax_status"] = "PENDING_ALLOCATION"
    event["total_tax_cents"] = 0
    event["total_workdays"] = 0
    event["blended_rate_bps"] = 0
    services.delete_tax_rows(event)
    store.touch(event)
    tranche["status"] = "VESTED"
    store.touch(tranche)
    outstanding = calc.outstanding_shares(services.tranches_of(grant["id"]))
    if outstanding != grant["outstanding_shares"]:
        grant["outstanding_shares"] = outstanding
        store.touch(grant)
    services.delete_pending_reports("VESTING_SETTLEMENT", event["id"])
    return envelope.ok(store.public(event))
