"""Kit issuance and void (PRD sections 3.4, 3.5).

Shared by the operator issuance endpoint and by every kit an auto-ship run
mints, so both drive the identical sizing, costing, reservation and program
recomputation path.
"""
from datetime import timedelta

import clock
import db
from errors import (
    ERR_CONTAINER_SIZE_NOT_PERMITTED,
    ERR_KIT_AUTHORIZATION_EXHAUSTED,
    ERR_NO_ELIGIBLE_CONTAINER_SIZE,
    ERR_PER_KIT_ALLOWANCE_EXCEEDED,
    ERR_PROGRAM_FUNDING_EXHAUSTED,
    fail,
)
from services import accounting, calc, lookup

OPEN_KIT_STATUSES = ("ISSUED", "ACTIVE_FILLING")

VOID_SUPERSEDED = "SUPERSEDED_BY_REPLACEMENT"
VOID_SHIPMENT_LOST = "SHIPMENT_LOST"
VOID_ENROLLMENT_PAUSED = "ENROLLMENT_PAUSED"
VOID_ENROLLMENT_TERMINATED = "ENROLLMENT_TERMINATED"


def most_recent_kit(enrollment_id, statuses=None):
    kits = lookup.enrollment_kits(enrollment_id)
    if statuses is not None:
        kits = [k for k in kits if k["status"] in statuses]
    if not kits:
        return None
    return kits[-1]


def non_voided_kit_count(enrollment_id):
    return len([k for k in lookup.enrollment_kits(enrollment_id) if k["status"] != "VOIDED"])


def plan_kit(enrollment, patient, state_rule, requested_size):
    """Sizing and costing: returns (container_size, required_units, cost)."""
    demand = calc.required_units(patient, enrollment)
    candidates = calc.candidate_sizes(patient, state_rule, demand)
    if not candidates:
        fail(ERR_NO_ELIGIBLE_CONTAINER_SIZE)
    if requested_size is not None:
        if requested_size not in candidates:
            fail(ERR_CONTAINER_SIZE_NOT_PERMITTED)
        size = requested_size
    else:
        size = candidates[0]
    return size, demand, calc.provisional_cost_cents(size)


def recompute_kits_issued(enrollment):
    enrollment["kits_issued"] = non_voided_kit_count(enrollment["id"])


def issue_kit(
    enrollment,
    program,
    plan,
    due_date_base,
    auto_ship_run_id=None,
    supersedes_override=False,
    supersedes_kit_id=None,
    check_pool=True,
):
    """The five ordered steps of PRD section 3.4."""
    container_size, demand, provisional = plan

    # STEP 1 -- supersession.
    prior = most_recent_kit(enrollment["id"], OPEN_KIT_STATUSES)
    superseded_id = None
    if prior is not None:
        prior["status"] = "VOIDED"
        prior["void_reason"] = VOID_SUPERSEDED
        db.bump(prior)
        accounting.release_reservation(program, prior, accounting.MEMO_KIT_SUPERSEDE)
        accounting.recompute_balances(program)
        superseded_id = prior["id"]

    # Gates evaluated against the world AFTER the supersede step.
    if non_voided_kit_count(enrollment["id"]) >= enrollment["kits_authorized"]:
        fail(ERR_KIT_AUTHORIZATION_EXHAUSTED)
    if provisional > program["per_kit_allowance_cents"]:
        fail(ERR_PER_KIT_ALLOWANCE_EXCEEDED)
    if check_pool and program["available_cents"] < provisional:
        fail(ERR_PROGRAM_FUNDING_EXHAUSTED)

    # STEP 2 -- mint the kit.
    issued_at = clock.now()
    catalogue = calc.constants.SIZE_CATALOG[container_size]
    kit = db.create_row(
        "kits",
        {
            "enrollment_id": enrollment["id"],
            "supersedes_kit_id": supersedes_kit_id if supersedes_override else superseded_id,
            "auto_ship_run_id": auto_ship_run_id,
            "container_size": container_size,
            "capacity_units": catalogue["capacity_units"],
            "volume_liters": float(catalogue["volume_liters"]),
            "required_units": demand,
            "fill_units": 0,
            "sealed_gross_weight_grams": None,
            "provisional_cost_cents": provisional,
            "issued_at": clock.fmt_instant(issued_at),
            "seal_deadline_date": calc.seal_deadline_date(issued_at, enrollment["cadence_days"]),
            "acknowledged_at": None,
            "status": "ISSUED",
            "void_reason": None,
        },
    )

    # STEP 3 -- the reservation append.
    accounting.append_entry(
        program, accounting.RESERVATION, provisional, kit["id"], accounting.MEMO_KIT_ISSUANCE
    )

    # STEP 4 -- program recomputation with the ACTIVE/EXHAUSTED evaluation.
    accounting.recompute_program(program)

    # STEP 5 -- the enrollment's own bookkeeping.
    enrollment["next_autoship_due_date"] = clock.fmt_date(
        due_date_base + timedelta(days=enrollment["cadence_days"])
    )
    recompute_kits_issued(enrollment)
    db.bump(enrollment)
    return kit


def void_kit(kit, void_reason, memo, program=None):
    """Move a kit to VOIDED and unwind its reservation. Returns the program."""
    if program is None:
        program = lookup.kit_program(kit)
    kit["status"] = "VOIDED"
    kit["void_reason"] = void_reason
    db.bump(kit)
    accounting.release_reservation(program, kit, memo)
    accounting.recompute_balances(program)
    return program
