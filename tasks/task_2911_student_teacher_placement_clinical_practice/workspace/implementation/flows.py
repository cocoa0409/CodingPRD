"""Cascades shared by several endpoints: accrual, settlement, removal."""

import calc
import clock
import derive
import store

REMOVAL_HOLD_NOTE = "CANCELLED_BY_REMOVAL"


def district_of_placement(placement):
    teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
    if teacher is None:
        return None
    return store.DISTRICTS.get(teacher["district_id"])


def _travel_enabled(placement):
    district = district_of_placement(placement)
    if district is None:
        return False
    return bool(district.get("travel_reimbursement_enabled"))


def _weekly_cents(placement):
    agreement = store.AGREEMENTS.get(placement["agreement_id"])
    teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
    if agreement is None or teacher is None:
        return 0
    return calc.weekly_stipend_cents(agreement["stipend_rate_cents_per_week"],
                                     teacher["consecutive_terms_hosted"])


def accrue_provisional(placement):
    """PRD 3.6: the provisional accrual raised at confirmation."""
    weekly = _weekly_cents(placement)
    weeks = int(placement["weeks_scheduled"])
    placement["stipend_variant"] = "PROVISIONAL"
    placement["stipend_weekly_cents"] = weekly
    placement["weeks_credited"] = weeks
    placement["stipend_gross_cents"] = calc.gross_stipend_cents(weekly, weeks, 0)
    placement["travel_reimbursement_cents"] = calc.travel_reimbursement_cents(
        placement["commute_miles"], weeks, _travel_enabled(placement))
    placement["stipend_status"] = "ACCRUED"
    store.touch(placement)


def settle_final(placement, premium_cents):
    """PRD 3.9: the FINAL settlement variant, credited on real weeks."""
    weekly = _weekly_cents(placement)
    weeks = calc.final_weeks_credited(placement["start_date"],
                                      placement["settlement_date"],
                                      placement["weeks_scheduled"])
    placement["stipend_variant"] = "FINAL"
    placement["stipend_weekly_cents"] = weekly
    placement["weeks_credited"] = weeks
    placement["stipend_gross_cents"] = calc.gross_stipend_cents(
        weekly, weeks, premium_cents)
    placement["travel_reimbursement_cents"] = calc.travel_reimbursement_cents(
        placement["commute_miles"], weeks, _travel_enabled(placement))
    store.touch(placement)


def refresh_agreement(placement):
    agreement = store.AGREEMENTS.get(placement["agreement_id"])
    if agreement is not None:
        derive.derive_agreement_ledger(agreement)
    return agreement


def refresh_supervisor(placement):
    supervisor = store.SUPERVISORS.get(placement["supervisor_id"])
    if supervisor is not None:
        derive.derive_supervisor(supervisor)
    return supervisor


def refresh_teacher(placement):
    teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
    if teacher is not None:
        derive.derive_teacher_counters(teacher)
    return teacher


def enter_removal_pending(placement, reason, requested_by_role,
                          requested_by_user_id, narrative):
    """ACTIVE -> REMOVAL_PENDING plus the three-hop cascade (PRD 3.8, 3.9)."""
    placement["placement_status"] = "REMOVAL_PENDING"
    placement["removal_reason"] = reason
    placement["removal_requested_by_role"] = requested_by_role
    placement["removal_requested_by_user_id"] = requested_by_user_id
    placement["removal_narrative"] = narrative
    store.touch(placement)
    derive.cancel_scheduled_cycles(placement, REMOVAL_HOLD_NOTE)
    derive.derive_placement_observations(placement, sweep=False)
    derive.derive_placement_points(placement)
    refresh_teacher(placement)
    refresh_supervisor(placement)
    refresh_agreement(placement)


def uphold_removal(placement, decided_by_user_id):
    """The four-level upheld-removal cascade (PRD 3.9)."""
    placement["placement_status"] = "REMOVED"
    placement["settlement_date"] = clock.today()
    placement["removal_decided_by_user_id"] = decided_by_user_id
    store.touch(placement)

    settle_final(placement, 0)
    derive.cancel_scheduled_cycles(placement, REMOVAL_HOLD_NOTE)
    derive.derive_placement_observations(placement, sweep=False)
    derive.derive_placement_points(placement)

    if placement["removal_reason"] == "COOPERATING_TEACHER_MISCONDUCT":
        if placement["stipend_status"] in ("ACCRUED", "APPROVED"):
            placement["stipend_status"] = "VOIDED"
            placement["stipend_gross_cents"] = 0
            store.touch(placement)
        teacher = store.TEACHERS.get(placement["cooperating_teacher_id"])
        if teacher is not None:
            teacher["qualification_status"] = "DISQUALIFIED"
            # PRD 3.4: disqualification_reason is taken from the removal
            # narrative, not from the removal_reason enum.
            teacher["disqualification_reason"] = placement["removal_narrative"]
            store.touch(teacher)

    refresh_teacher(placement)
    refresh_supervisor(placement)
    refresh_agreement(placement)

    request_row = store.REQUESTS.get(placement["request_id"])
    if request_row is not None:
        request_row["status"] = "SUBMITTED"
        teacher_id = placement["cooperating_teacher_id"]
        if teacher_id not in request_row["excluded_cooperating_teacher_ids"]:
            request_row["excluded_cooperating_teacher_ids"].append(teacher_id)
        store.touch(request_row)
