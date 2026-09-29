"""Transitional living: placements, savings ledger, life skills, reviews, exit.

PRD 3.7 and 3.8.
"""

from flask import Blueprint, request

import authz
import calc
import cascade
import envelope
import find
import serial
import shape
import store
from errors import fail

bp = Blueprint("tlp", __name__)

TENANCY_STATUSES = ("PLACED", "NOTICE_GIVEN", "EXITED")
COMPLIANCE_STATUSES = ("IN_COMPLIANCE", "SAVINGS_DEFICIENT", "PROBATION")
ENTRY_TYPES = ("DEPOSIT", "WITHDRAWAL", "REVERSAL")
MODULE_CODES = (
    "BUDGETING",
    "TENANCY",
    "EMPLOYMENT_READINESS",
    "HEALTH_LITERACY",
    "CONFLICT_RESOLUTION",
    "CIVIC_ENGAGEMENT",
)
EXIT_REASONS = (
    "DURATION_LIMIT",
    "INDEPENDENT_HOUSING",
    "REUNIFIED",
    "NONCOMPLIANCE",
    "YOUTH_INITIATED",
)


# ------------------------------------------------------------------- placement
@bp.post("/ryhs/tlp-placements")
def create_placement():
    user_id, _role = authz.require(authz.TLP_COORDINATOR)
    body = shape.body()
    # Ladder 5 - body foreign keys in declared input order.
    youth = shape.fk_lookup(body, "youth_id", store.youths, "ERR_YOUTH_NOT_FOUND")
    program = shape.fk_lookup(body, "program_id", store.programs, "ERR_PROGRAM_NOT_FOUND")
    # Ladder 6.
    if youth is None:
        shape.need_str(body, "youth_id", 1, 10000)
    if program is None:
        shape.need_str(body, "program_id", 1, 10000)
    income = shape.opt_int(body, "documented_monthly_income_cents", 0, None, 0)

    # Ladder 19 - an escalated screening blocks the action outright.
    screening = calc.latest_screening(youth["id"])
    if screening is not None and screening["status"] == "ESCALATED":
        fail("ERR_SCREENING_ESCALATED_BLOCKS_ACTION")
    # Ladder 25 - the licensed age band, both bounds inclusive.
    age = calc.age_years(youth)
    if age < program["min_age_years"] or age > program["max_age_years"]:
        fail("ERR_AGE_OUTSIDE_PROGRAM_BAND")
    # Ladder 26.
    if program["program_type"] != "TRANSITIONAL_LIVING":
        fail("ERR_PROGRAM_TYPE_MISMATCH")
    # Ladder 30 - a cleared screening must exist.
    if screening is None or screening["status"] != "CLEARED":
        fail("ERR_SCREENING_REQUIRED")
    # Ladder 31 - point-in-time exclusivity, no end instant participates.
    for other in store.tlp_placements.values():
        if other["youth_id"] != youth["id"]:
            continue
        if other["tenancy_status"] in calc.OPEN_TENANCY_STATUSES:
            fail("ERR_PLACEMENT_OVERLAP")
    # Ladder 43 - the licensed bed capacity is a hard federal ceiling and there is
    # no waitlist in transitional living at all.
    if program["occupied_beds"] >= program["licensed_bed_capacity"]:
        fail("ERR_BED_CAPACITY_EXCEEDED")
    # Ladder 48 - the lowest-priority gate.
    if youth["risk_posture"] != "OPEN":
        fail("ERR_YOUTH_POSTURE_RESTRICTED")

    placement = store.stamp_new(
        {
            "youth_id": youth["id"],
            "program_id": program["id"],
            "tenancy_status": "PLACED",
            "compliance_status": "IN_COMPLIANCE",
            "placed_at": store.now(),
            "documented_monthly_income_cents": income,
            "days_elapsed": 0,
            "base_allowance_days": program["max_placement_days"],
            "earned_bonus_days": 0,
            "allowance_days": program["max_placement_days"],
            "consumed_ratio_bp": 0,
            "life_skills_credit_hours": 0,
            "required_savings_cents": 0,
            "savings_balance_cents": 0,
            "match_awarded_cents": 0,
            "consecutive_probation_reviews": 0,
            "exited_at": None,
            "exit_reason": None,
            "coordinator_user_id": user_id,
        }
    )
    cascade.apply_placement_derived(placement)
    store.tlp_placements[placement["id"]] = placement

    program["occupied_beds"] += 1
    cascade.refresh_program(program)

    youth["status"] = "TLP_ENROLLED"
    cascade.apply_youth_derived(youth)
    store.touch(youth)
    return envelope.created(serial.placement(placement))


@bp.get("/ryhs/tlp-placements")
def list_placements():
    authz.require(authz.PROGRAM_ADMIN, authz.TLP_COORDINATOR, authz.SHELTER_CASE_MANAGER)
    youth_id = request.args.get("youth_id")
    program_id = request.args.get("program_id")
    tenancy = envelope.enum_filter("tenancy_status", TENANCY_STATUSES)
    compliance = envelope.enum_filter("compliance_status", COMPLIANCE_STATUSES)
    envelope.page_args()
    rows = []
    for placement in store.ordered(list(store.tlp_placements.values())):
        if youth_id is not None and placement["youth_id"] != youth_id:
            continue
        if program_id is not None and placement["program_id"] != program_id:
            continue
        if tenancy is not None and placement["tenancy_status"] != tenancy:
            continue
        if compliance is not None and placement["compliance_status"] != compliance:
            continue
        rows.append(placement)
    return envelope.listing(rows, serial.placement)


@bp.get("/ryhs/tlp-placements/<placement_id>")
def read_placement(placement_id):
    authz.require(authz.PROGRAM_ADMIN, authz.TLP_COORDINATOR, authz.SHELTER_CASE_MANAGER)
    placement = find.placement(placement_id)
    return envelope.ok(serial.placement(placement))


# ---------------------------------------------------------- savings ledger
def _refresh_youth_lifetime(youth):
    """PRD 3.8: posting an entry recomputes the youth's lifetime deposits.

    Per PRD 2.8 the touched youth row refreshes its own audit fields, so the bump
    happens exactly when the recomputed figure actually moved.
    """
    if youth is None:
        return
    total = calc.lifetime_deposited_cents(youth["id"])
    if youth["lifetime_savings_deposited_cents"] != total:
        youth["lifetime_savings_deposited_cents"] = total
        store.touch(youth)


@bp.post("/ryhs/tlp-placements/<placement_id>/savings-entries")
def post_savings_entry(placement_id):
    user_id, _role = authz.require(authz.TLP_COORDINATOR)
    placement = find.placement(placement_id)
    body = shape.body()
    # Ladder 6.
    entry_type = shape.need_enum(body, "entry_type", ENTRY_TYPES)
    amount = shape.need_int(body, "amount_cents", 1, None)
    expected = shape.need_int(body, "expected_placement_version")
    source_note = shape.opt_str(body, "source_note", 0, 200)

    # Ladder 8 - optimistic concurrency on the placement (PRD 2.9).
    if expected != placement["version"]:
        fail("ERR_STALE_PLACEMENT_VERSION")
    # Ladder 16.
    if placement["tenancy_status"] == "EXITED":
        fail("ERR_PLACEMENT_ALREADY_EXITED")

    cascade.apply_placement_derived(placement)
    if entry_type == "WITHDRAWAL":
        # Ladder 44.
        if amount > placement["savings_balance_cents"]:
            fail("ERR_SAVINGS_INSUFFICIENT_BALANCE")
        # Ladder 45 - savings are locked while a youth is on probation.
        if placement["compliance_status"] == "PROBATION":
            fail("ERR_SAVINGS_WITHDRAWAL_BLOCKED")
    if entry_type == "REVERSAL":
        # Ladder 46 - a reversal can never invent savings never deposited.
        if amount > calc.deposit_headroom(placement["id"]):
            fail("ERR_SAVINGS_REVERSAL_UNMATCHED")

    program = store.programs.get(placement["program_id"])
    rate_bp = program["savings_match_rate_bp"] if program is not None else 0
    entry = store.stamp_new(
        {
            "placement_id": placement["id"],
            "entry_type": entry_type,
            "amount_cents": amount,
            "signed_amount_cents": calc.signed_amount(entry_type, amount),
            "match_component_cents": calc.match_component(entry_type, amount, rate_bp),
            "balance_after_cents": 0,
            "posted_at": store.now(),
            "source_note": source_note,
            "recorded_by_user_id": user_id,
        },
        versioned=False,
    )
    store.savings_entries[entry["id"]] = entry

    # The placement's totals are recomputed over every entry, then frozen onto this
    # entry as the balance immediately after it posted.
    cascade.apply_placement_derived(placement)
    entry["balance_after_cents"] = placement["savings_balance_cents"]
    store.touch(placement)

    _refresh_youth_lifetime(store.youths.get(placement["youth_id"]))
    return envelope.created(serial.savings_entry(entry))


@bp.get("/ryhs/tlp-placements/<placement_id>/savings-entries")
def list_savings_entries(placement_id):
    authz.require(authz.PROGRAM_ADMIN, authz.TLP_COORDINATOR)
    placement = find.placement(placement_id)
    entry_type = envelope.enum_filter("entry_type", ENTRY_TYPES)
    envelope.page_args()
    rows = [
        e
        for e in calc.placement_entries(placement["id"])
        if entry_type is None or e["entry_type"] == entry_type
    ]
    return envelope.listing(rows, serial.savings_entry)


# ------------------------------------------------------------- life skills
@bp.post("/ryhs/tlp-placements/<placement_id>/life-skills-completions")
def credit_life_skills(placement_id):
    user_id, _role = authz.require(authz.TLP_COORDINATOR)
    placement = find.placement(placement_id)
    body = shape.body()
    module_code = shape.need_enum(body, "module_code", MODULE_CODES)
    credit_hours = shape.need_int(body, "credit_hours", 1, 40)

    # Ladder 16.
    if placement["tenancy_status"] == "EXITED":
        fail("ERR_PLACEMENT_ALREADY_EXITED")
    # Ladder 37 - a placement that has consumed its allowance must simply be exited.
    cascade.apply_placement_derived(placement)
    if placement["days_elapsed"] >= placement["allowance_days"]:
        fail("ERR_DURATION_LIMIT_REACHED")

    completion = store.stamp_new(
        {
            "placement_id": placement["id"],
            "module_code": module_code,
            "credit_hours": credit_hours,
            "completed_at": store.now(),
            "verified_by_user_id": user_id,
        },
        versioned=False,
    )
    store.life_skills_completions[completion["id"]] = completion

    placement["life_skills_credit_hours"] += credit_hours
    cascade.apply_placement_derived(placement)
    store.touch(placement)
    return envelope.created(serial.life_skills(completion))


@bp.get("/ryhs/tlp-placements/<placement_id>/life-skills-completions")
def list_life_skills(placement_id):
    authz.require(authz.PROGRAM_ADMIN, authz.TLP_COORDINATOR)
    placement = find.placement(placement_id)
    envelope.page_args()
    rows = store.ordered(
        [
            c
            for c in store.life_skills_completions.values()
            if c["placement_id"] == placement["id"]
        ]
    )
    return envelope.listing(rows, serial.life_skills)


# ------------------------------------------------------- compliance review
@bp.post("/ryhs/tlp-placements/<placement_id>/compliance-review")
def compliance_review(placement_id):
    authz.require(authz.TLP_COORDINATOR, authz.PROGRAM_ADMIN)
    placement = find.placement(placement_id)

    # Ladder 16.
    if placement["tenancy_status"] == "EXITED":
        fail("ERR_PLACEMENT_ALREADY_EXITED")
    # Ladder 37.
    cascade.apply_placement_derived(placement)
    if placement["days_elapsed"] >= placement["allowance_days"]:
        fail("ERR_DURATION_LIMIT_REACHED")

    outcome = calc.review_outcome(
        placement["savings_balance_cents"], placement["required_savings_cents"]
    )
    placement["compliance_status"] = outcome
    if outcome == "PROBATION":
        placement["consecutive_probation_reviews"] += 1
    else:
        placement["consecutive_probation_reviews"] = 0
    # The single coupling between the two dimensions.
    if placement["consecutive_probation_reviews"] >= 2 and placement["tenancy_status"] == "PLACED":
        placement["tenancy_status"] = "NOTICE_GIVEN"
    store.touch(placement)
    return envelope.ok(serial.placement(placement))


# -------------------------------------------------------------------- exit
@bp.post("/ryhs/tlp-placements/<placement_id>/exit")
def exit_placement(placement_id):
    authz.require(authz.TLP_COORDINATOR)
    placement = find.placement(placement_id)
    body = shape.body()
    exit_reason = shape.need_enum(body, "exit_reason", EXIT_REASONS)

    # Ladder 16 - a second exit is refused.
    if placement["tenancy_status"] == "EXITED":
        fail("ERR_PLACEMENT_ALREADY_EXITED")

    placement["tenancy_status"] = "EXITED"
    placement["exited_at"] = store.now()
    placement["exit_reason"] = exit_reason
    cascade.apply_placement_derived(placement)
    store.touch(placement)

    program = store.programs.get(placement["program_id"])
    if program is not None:
        program["occupied_beds"] = max(0, program["occupied_beds"] - 1)
        cascade.refresh_program(program)

    youth = store.youths.get(placement["youth_id"])
    if youth is not None:
        youth["status"] = "EXITED"
        cascade.apply_youth_derived(youth)
        store.touch(youth)
    return envelope.ok(serial.placement(placement))
