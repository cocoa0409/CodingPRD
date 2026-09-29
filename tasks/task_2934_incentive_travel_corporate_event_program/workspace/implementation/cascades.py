"""Ordered, total cascades (PRD 2.10, 3.1, 3.4, 3.8, 3.9).

Every row a cascade touches is version-incremented exactly as a direct
mutation would be, and no cascade stops early because a step found nothing.
"""

import calc
import serialize
from store import db, parse_dt

NON_TERMINAL_AIR = ("REQUESTED", "TICKETED", "CHANGE_PENDING")
NON_TERMINAL_ATTENDANCE = ("INVITED", "ACCEPTED", "CONFIRMED")
LIVE_SIGNUP = ("BOOKED", "WAITLISTED")


def _program_of(row_program_id):
    return db.programs.get(row_program_id)


def _void_air(registration):
    if registration["air_status"] in NON_TERMINAL_AIR:
        registration["air_status"] = "VOIDED"


def _refresh_hotel_ledgers(program_id):
    """Re-derive the room-night ledger on every executed hotel contract."""
    for contract in db.supplier_contracts.values():
        if (contract["program_id"] == program_id
                and contract["supplier_kind"] == "HOTEL"
                and contract["status"] == "EXECUTED"):
            calc.room_night_ledger(db, contract)


# ------------------------------------------------------- 3.4 execution cascade
def execute_contract(contract, actor):
    program = _program_of(contract["program_id"])

    # Level 1 - the contract itself.
    contract["status"] = "EXECUTED"
    contract["executed_by_user_id"] = actor.user_id
    contract["executed_at"] = db.logical_now()
    contract["room_nights_blocked"] = (contract["room_block_count"]
                                       * contract["contracted_nights"])
    calc.room_night_ledger(db, contract)
    db.touch(contract)

    is_hotel = contract["supplier_kind"] == "HOTEL"
    selected = None

    if is_hotel:
        # Level 2 - the referenced destination is selected.
        selected = db.destinations.get(contract["destination_id"])
        if selected is not None and selected["status"] == "SHORTLISTED":
            selected["status"] = "SELECTED"
            db.touch(selected)

        # Level 3 - every sibling still in play is turned down.
        for sibling in db.ordered(db.destinations):
            if sibling["program_id"] != contract["program_id"]:
                continue
            if selected is not None and sibling["id"] == selected["id"]:
                continue
            if sibling["status"] in ("CANDIDATE", "SHORTLISTED"):
                sibling["status"] = "REJECTED"
                db.touch(sibling)

        # Level 4 - the program, only out of SOURCING.
        if program is not None and program["status"] == "SOURCING":
            program["status"] = "CONTRACTED"
            if selected is not None:
                program["per_person_cost_basis_cents"] = selected["per_person_cost_cents"]
            for qualifier in db.ordered(db.qualifiers):
                if qualifier["program_id"] != program["id"]:
                    continue
                if qualifier["award_status"] not in ("QUALIFIED", "NOTIFIED", "REGISTERED"):
                    continue
                qualifier["committed_cost_cents"] = calc.qualifier_committed_cost(db, qualifier)
                db.touch(qualifier)
            calc.program_budget_rollup(db, program)
            calc.program_counts(db, program)
            calc.program_cancellation_exposure(db, program)
            db.touch(program)
        elif program is not None:
            calc.program_cancellation_exposure(db, program)

    # Level 5 - the deposit schedule of THIS contract.
    if program is not None and program["budget_posture"] == "OVERCOMMITTED":
        for milestone in db.ordered(db.deposit_milestones):
            if milestone["contract_id"] != contract["id"]:
                continue
            if milestone["status"] != "SCHEDULED":
                continue
            milestone["requires_finance_review"] = True
            db.touch(milestone)

    return contract


def withdraw_contract(contract, reason):
    contract["status"] = "WITHDRAWN"
    contract["withdrawal_reason"] = reason
    for milestone in db.ordered(db.deposit_milestones):
        if milestone["contract_id"] == contract["id"] and milestone["status"] == "SCHEDULED":
            milestone["status"] = "CANCELLED"
            db.touch(milestone)
    db.touch(contract)
    return contract


# ---------------------------------------------- 3.1 registration window closes
def close_registration_window(program):
    for registration in db.ordered(db.registrations):
        if registration["program_id"] != program["id"]:
            continue
        if registration["attendance_status"] != "INVITED":
            continue
        registration["attendance_status"] = "CANCELLED"
        registration["cancellation_reason"] = "REGISTRATION_WINDOW_CLOSED"
        db.touch(registration)
    return program


# ------------------------------------------------------- 3.9 reconciliation
def reconcile(program):
    for registration in db.ordered(db.registrations):
        if registration["program_id"] != program["id"]:
            continue
        if registration["attendance_status"] == "CONFIRMED":
            registration["attendance_status"] = "TRAVELLED"
            db.touch(registration)

    for qualifier in db.ordered(db.qualifiers):
        if qualifier["program_id"] != program["id"]:
            continue
        if qualifier["award_status"] != "REGISTERED":
            continue
        qualifier["award_status"] = "TRAVELLED"
        qualifier["taxable_award_cents"] = calc.taxable_award_base(
            qualifier["committed_cost_cents"])
        if qualifier["taxable_award_cents"] > 0 and qualifier["tax_status"] == "NOT_APPLICABLE":
            qualifier["tax_status"] = "PENDING_REPORT"
        db.touch(qualifier)

    measurement = calc.program_measurement(db, program)
    program["sales_lift_pct"] = measurement["sales_lift_pct"]
    program["satisfaction_index"] = measurement["satisfaction_index"]
    _refresh_hotel_ledgers(program["id"])
    serialize.refresh_program(program)
    return program


# ------------------------------------------------- 3.9 program cancellation
def cancel_program(program, reason):
    program["cancellation_reason"] = reason

    # 1. seats.
    touched_registration_ids = []
    for registration in db.ordered(db.registrations):
        if registration["program_id"] != program["id"]:
            continue
        if registration["attendance_status"] not in NON_TERMINAL_ATTENDANCE:
            continue
        registration["attendance_status"] = "CANCELLED"
        _void_air(registration)
        db.touch(registration)
        touched_registration_ids.append(registration["id"])

    # 2. their activity signups - no promotion runs here.
    for signup in db.ordered(db.activity_signups):
        if signup["registration_id"] not in touched_registration_ids:
            continue
        if signup["status"] not in LIVE_SIGNUP:
            continue
        signup["status"] = "CANCELLED"
        db.touch(signup)

    # 3. open activities, taking their remaining live signups with them.
    for activity in db.ordered(db.onsite_activities):
        if activity["program_id"] != program["id"] or activity["status"] != "OPEN":
            continue
        activity["status"] = "CANCELLED"
        for signup in db.ordered(db.activity_signups):
            if signup["activity_id"] != activity["id"]:
                continue
            if signup["status"] not in LIVE_SIGNUP:
                continue
            signup["status"] = "CANCELLED"
            db.touch(signup)
        calc.activity_counts(db, activity)
        db.touch(activity)

    # 4. qualifiers still in play.
    for qualifier in db.ordered(db.qualifiers):
        if qualifier["program_id"] != program["id"]:
            continue
        if qualifier["award_status"] not in ("QUALIFIED", "NOTIFIED", "REGISTERED"):
            continue
        qualifier["award_status"] = "WITHDRAWN"
        qualifier["committed_cost_cents"] = 0
        db.touch(qualifier)

    # 5. the deposit schedules of every executed contract, against the clock.
    now = parse_dt(db.logical_now())
    for contract in db.ordered(db.supplier_contracts):
        if contract["program_id"] != program["id"] or contract["status"] != "EXECUTED":
            continue
        for milestone in db.ordered(db.deposit_milestones):
            if milestone["contract_id"] != contract["id"]:
                continue
            if milestone["status"] == "PAID":
                due = parse_dt(milestone["due_at"])
                milestone["status"] = "FORFEITED" if (due is not None and due <= now) else "REFUNDED"
                db.touch(milestone)
            elif milestone["status"] == "SCHEDULED":
                milestone["status"] = "CANCELLED"
                db.touch(milestone)
        calc.room_night_ledger(db, contract)

    # 6. the exposure is re-stamped over the same contracts.
    program["status"] = "CANCELLED"
    calc.program_cancellation_exposure(db, program)
    serialize.refresh_program(program)
    db.touch(program)
    return program


# --------------------------------------------------- 3.9 seat cancellation
def cancel_registration(registration, reason):
    previous = registration["attendance_status"]
    registration["cancellation_reason"] = reason
    registration["attendance_status"] = "CANCELLED"
    _void_air(registration)

    if previous == "CONFIRMED":
        # Dependent guest seats.
        for guest in db.ordered(db.registrations):
            if guest.get("guest_of_registration_id") != registration["id"]:
                continue
            if guest["registration_kind"] != "GUEST":
                continue
            if guest["attendance_status"] not in NON_TERMINAL_ATTENDANCE:
                continue
            guest["attendance_status"] = "CANCELLED"
            db.touch(guest)

        # This seat's own activity slots, with one promotion per released seat.
        released_activity_ids = []
        for signup in db.ordered(db.activity_signups):
            if signup["registration_id"] != registration["id"]:
                continue
            if signup["status"] not in LIVE_SIGNUP:
                continue
            was_booked = signup["status"] == "BOOKED"
            signup["status"] = "CANCELLED"
            db.touch(signup)
            if was_booked:
                released_activity_ids.append(signup["activity_id"])

        for activity_id in released_activity_ids:
            activity = db.onsite_activities.get(activity_id)
            if activity is None:
                continue
            calc.promote_one(db, activity)
            calc.activity_counts(db, activity)

        _refresh_hotel_ledgers(registration["program_id"])

        program = _program_of(registration["program_id"])
        if program is not None:
            calc.program_budget_rollup(db, program)

        if registration["registration_kind"] == "WINNER":
            qualifier = db.qualifiers.get(registration["qualifier_id"])
            if qualifier is not None and qualifier["award_status"] == "REGISTERED":
                remaining = [r for r in db.registrations.values()
                             if r["qualifier_id"] == qualifier["id"]
                             and r["registration_kind"] == "WINNER"
                             and r["attendance_status"] != "CANCELLED"
                             and r["id"] != registration["id"]]
                if not remaining:
                    qualifier["award_status"] = "NOTIFIED"
                    db.touch(qualifier)

    db.touch(registration)
    return registration


# ------------------------------------------------------- 3.8 activity closure
def close_activity(activity):
    activity["status"] = "CLOSED"
    for signup in db.ordered(db.activity_signups):
        if signup["activity_id"] != activity["id"]:
            continue
        if signup["status"] != "WAITLISTED":
            continue
        signup["status"] = "CANCELLED"
        db.touch(signup)
    calc.activity_counts(db, activity)
    db.touch(activity)
    return activity
