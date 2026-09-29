"""Participants, insider reclassification, the termination cascade and mobility periods."""

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

bp = Blueprint("participants", __name__)

READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR, PARTICIPANT)
LIST_READERS = (PLAN_ADMIN, COMPLIANCE, AUDITOR)
INSIDER_STATUSES = ("NON_INSIDER", "DESIGNATED_INSIDER", "SECTION_16_OFFICER")
TERMINATION_REASONS = ("VOLUNTARY", "INVOLUNTARY", "FOR_CAUSE", "RETIREMENT", "DEATH")


def reference_date(row):
    if row["employment_status"] == "TERMINATED" and row["termination_date"]:
        return clock.parse_date(row["termination_date"])
    return clock.today()


def serialize(row):
    out = store.public(row)
    age, service = calc.age_and_service(
        clock.parse_date(row["birth_date"]),
        clock.parse_date(row["hire_date"]),
        reference_date(row),
    )
    out["age_years"] = age
    out["service_years"] = service
    out["retirement_eligible"] = calc.retirement_eligible(age, service)
    return out


@bp.route("/participants", methods=["POST"])
def create_participant():
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    row = store.base_row()
    row.update({
        "full_name": validate.field_str(body, "full_name"),
        "employee_number": validate.field_str(body, "employee_number"),
        "home_country_code": validate.field_str(body, "home_country_code"),
        "home_state_code": validate.field_str(body, "home_state_code", required=False),
        "hire_date": clock.fmt_date(validate.field_date(body, "hire_date")),
        "birth_date": clock.fmt_date(validate.field_date(body, "birth_date")),
        "insider_status": validate.field_enum(
            body, "insider_status", INSIDER_STATUSES, required=False, default="NON_INSIDER"),
        "employment_status": "ACTIVE",
        "termination_date": None,
        "termination_reason": None,
        "ptep_expiry_date": None,
    })
    for other in store.participants.values():
        if other["employee_number"] == row["employee_number"]:
            raise ApiError("ERR_DUPLICATE_EMPLOYEE_NUMBER")
    store.participants[row["id"]] = row
    return envelope.created(serialize(row))


@bp.route("/participants", methods=["GET"])
def list_participants():
    auth.begin(*LIST_READERS)
    rows = list(store.participants.values())
    employment = request.args.get("employment_status")
    if employment is not None:
        rows = [r for r in rows if r["employment_status"] == employment]
    insider = request.args.get("insider_status")
    if insider is not None:
        rows = [r for r in rows if r["insider_status"] == insider]
    return envelope.page(store.sort_default(rows), serialize)


@bp.route("/participants/<participant_id>", methods=["GET"])
def read_participant(participant_id):
    actor = auth.begin(*READERS)
    auth.scope(actor, participant_id)
    return envelope.ok(serialize(services.participant_or_404(participant_id)))


@bp.route("/participants/<participant_id>/insider-status", methods=["POST"])
def reclassify(participant_id):
    actor = auth.begin(COMPLIANCE)
    row = services.participant_or_404(participant_id)
    status = validate.field_enum(actor.body, "insider_status", INSIDER_STATUSES)
    if row["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    row["insider_status"] = status
    store.touch(row)
    return envelope.ok(serialize(row))


@bp.route("/participants/<participant_id>/terminate", methods=["POST"])
def terminate(participant_id):
    actor = auth.begin(PLAN_ADMIN)
    row = services.participant_or_404(participant_id)
    body = actor.body
    termination_date = validate.field_date(body, "termination_date")
    reason = validate.field_enum(body, "termination_reason", TERMINATION_REASONS)
    fmv = validate.field_int(
        body, "acceleration_fmv_per_share_cents", required=False, minimum=1)
    if row["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_INVALID_STATE")
    if termination_date < clock.parse_date(row["hire_date"]):
        raise ApiError("ERR_PARTICIPANT_INVALID_STATE")

    age, service = calc.age_and_service(
        clock.parse_date(row["birth_date"]),
        clock.parse_date(row["hire_date"]),
        termination_date,
    )
    eligible = calc.retirement_eligible(age, service)
    horizon = clock.add_days(termination_date, 365)

    # Resolve every tranche movement before writing anything (atomicity).
    moves = []
    for grant in services.grants_of_participant(participant_id):
        if grant["status"] not in ("GRANTED", "PARTIALLY_FORFEITED"):
            continue
        for tranche in services.tranches_of(grant["id"]):
            if tranche["status"] == "UNVESTED":
                if reason == "DEATH":
                    moves.append((grant, tranche, "ACCELERATE", "DEATH"))
                elif (reason == "RETIREMENT" and eligible
                      and clock.parse_date(tranche["scheduled_vest_date"]) <= horizon):
                    moves.append((grant, tranche, "ACCELERATE", "RETIREMENT_ELIGIBILITY"))
                else:
                    moves.append((grant, tranche, "FORFEIT", None))
            elif tranche["status"] == "VESTED" and reason == "FOR_CAUSE":
                if not services.tranche_has_settled_event(tranche["id"]):
                    moves.append((grant, tranche, "CLAWBACK", None))
    if fmv is None and any(action == "ACCELERATE" for _g, _t, action, _r in moves):
        raise ApiError("ERR_ACCELERATION_FMV_REQUIRED")

    row["employment_status"] = "TERMINATED"
    row["termination_date"] = clock.fmt_date(termination_date)
    row["termination_reason"] = reason
    row["ptep_expiry_date"] = clock.fmt_date(calc.ptep_expiry(termination_date, reason))

    # Hop 1 - tranche level.
    touched_grants = {}
    for grant, tranche, action, accel_reason in moves:
        touched_grants[grant["id"]] = grant
        if action == "ACCELERATE":
            tranche["status"] = "VESTED"
            tranche["acceleration_reason"] = accel_reason
            tranche["vested_at"] = clock.fmt_instant(clock.now())
            store.touch(tranche)
            services.new_vesting_event(tranche, grant, fmv, "SHARE_WITHHOLD", clock.now())
        elif action == "FORFEIT":
            tranche["status"] = "FORFEITED"
            store.touch(tranche)
        else:  # CLAWBACK
            tranche["status"] = "FORFEITED"
            store.touch(tranche)
            services.reverse_pending_tax_events(tranche, "FOR_CAUSE_CLAWBACK")

    # Hop 2 - grant level.
    decreases = {}
    for grant in touched_grants.values():
        plan = services.plan_of_grant(grant)
        delta = services.recompute_grant_shares(grant, plan)
        destination = services.forfeiture_grant_status(
            grant, services.tranches_of(grant["id"]))
        if destination is not None:
            grant["status"] = destination
            if destination == "FORFEITED":
                # Both figures already recompute to 0 here; write them explicitly.
                grant["weighted_reserve_shares"] = 0
                grant["outstanding_shares"] = 0
        if delta < 0:
            decreases[plan["id"]] = decreases.get(plan["id"], 0) + (-delta)
        store.touch(grant)

    # Hops 3 and 4 - plan level.
    for plan_id, decrease in decreases.items():
        plan = store.plans[plan_id]
        plan["shares_returned_cumulative"] += decrease
        plan["fiscal_year_returned_shares"] += decrease
        services.recompute_reserve(plan)
        services.recompute_burn_rates(plan)
        store.touch(plan)

    # Independent fan-out over trading plans and preclearance requests.
    for tplan in store.sort_default(
        [t for t in store.trading_plans.values() if t["participant_id"] == participant_id]
    ):
        if tplan["status"] in ("PENDING_COOLING_OFF", "EFFECTIVE"):
            tplan["status"] = "TERMINATED"
            tplan["termination_reason"] = "EMPLOYMENT_TERMINATED"
            store.touch(tplan)
    affected_windows = []
    for req in store.sort_default(
        [p for p in store.preclearances.values() if p["participant_id"] == participant_id]
    ):
        if req["status"] in ("SUBMITTED", "INFO_REQUESTED", "APPROVED"):
            req["status"] = "VOID"
            store.touch(req)
            affected_windows.append(req["window_id"])
    for window_id in dict.fromkeys(affected_windows):
        window = store.windows.get(window_id)
        if window is not None:
            services.recompute_window_cumulative(window)

    store.touch(row)
    return envelope.ok(serialize(row))


# --- mobility assignments ---------------------------------------------------

MAX_DATE = clock.parse_date("9999-12-31")


@bp.route("/mobility-assignments", methods=["POST"])
def create_assignment():
    actor = auth.begin(PLAN_ADMIN)
    body = actor.body
    reference = validate.raw_id(body, "participant_id")
    if reference is not None:
        services.participant_or_404(reference)
    participant_id = validate.field_id(body, "participant_id")
    participant = services.participant_or_404(participant_id)
    start_date = validate.field_date(body, "start_date")
    end_date = validate.field_date(body, "end_date", required=False)
    validate.require_order(start_date, end_date, "end_date precedes start_date.")
    row = store.base_row(versioned=False)
    row.update({
        "participant_id": participant_id,
        "jurisdiction_code": validate.field_str(
            body, "jurisdiction_code", min_len=2, max_len=8),
        "tax_rate_bps": validate.field_int(body, "tax_rate_bps", minimum=0, maximum=10000),
        "start_date": clock.fmt_date(start_date),
        "end_date": clock.fmt_date(end_date),
        "workdays": validate.field_int(body, "workdays", minimum=0),
    })
    if participant["employment_status"] != "ACTIVE":
        raise ApiError("ERR_PARTICIPANT_NOT_ACTIVE")
    new_end = end_date if end_date is not None else MAX_DATE
    for other in store.assignments.values():
        if other["participant_id"] != participant_id:
            continue
        other_start = clock.parse_date(other["start_date"])
        other_end = (clock.parse_date(other["end_date"])
                     if other["end_date"] is not None else MAX_DATE)
        if start_date <= other_end and other_start <= new_end:
            raise ApiError("ERR_ASSIGNMENT_PERIOD_OVERLAP")
    store.assignments[row["id"]] = row
    return envelope.created(store.public(row))


@bp.route("/mobility-assignments/<assignment_id>", methods=["GET"])
def read_assignment(assignment_id):
    auth.begin(*READERS)
    row = store.assignments.get(assignment_id)
    if row is None:
        raise ApiError("ERR_ASSIGNMENT_NOT_FOUND")
    return envelope.ok(store.public(row))


@bp.route("/participants/<participant_id>/mobility-assignments", methods=["GET"])
def list_assignments(participant_id):
    actor = auth.begin(*READERS)
    auth.scope(actor, participant_id)
    services.participant_or_404(participant_id)
    rows = [a for a in store.assignments.values() if a["participant_id"] == participant_id]
    code = request.args.get("jurisdiction_code")
    if code is not None:
        rows = [r for r in rows if r["jurisdiction_code"] == code]
    return envelope.page(store.sort_by(rows, "start_date"))


@bp.route("/participants/<participant_id>/transaction-reports", methods=["GET"])
def list_reports(participant_id):
    actor = auth.begin(*READERS)
    auth.scope(actor, participant_id)
    services.participant_or_404(participant_id)
    rows = [r for r in store.reports.values() if r["participant_id"] == participant_id]
    status = request.args.get("status")
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    form_type = request.args.get("form_type")
    if form_type is not None:
        rows = [r for r in rows if r["form_type"] == form_type]
    return envelope.page(store.sort_by(rows, "transaction_at"))
