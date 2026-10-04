"""Member posture cascades shared by the audit, award and recall paths."""

import clock
import store
from services import ledger


def suspend_active_programs(member):
    """Every ACTIVE program of the member -> SUSPENDED; its future SCHEDULED
    pickups -> MISSED."""
    for program in store.ordered(store.programs.values()):
        if program["member_id"] != member["id"] or program["program_status"] != "ACTIVE":
            continue
        program["program_status"] = "SUSPENDED"
        store.touch(program)
        for pickup in store.ordered(store.pickups.values()):
            if pickup["program_id"] != program["id"] or pickup["pickup_status"] != "SCHEDULED":
                continue
            if pickup["scheduled_date"].date() >= clock.today():
                pickup["pickup_status"] = "MISSED"
                store.touch(pickup)


def activate_pending_programs(member, from_status="PENDING"):
    """Certification / reinstatement cascade: programs -> ACTIVE."""
    for program in store.ordered(store.programs.values()):
        if program["member_id"] != member["id"] or program["program_status"] != from_status:
            continue
        program["program_status"] = "ACTIVE"
        store.touch(program)


def withdraw_submitted_bids(member, reason):
    """Withdraw every SUBMITTED bid of the member, releasing each hold."""
    for bid in ledger.submitted_bids_of(member["id"]):
        bid["bid_status"] = "WITHDRAWN"
        bid["rejection_reason"] = reason
        store.touch(bid)
        ledger.append_entry(member, "BID_RELEASE", bid["shares_offered"],
                            reference_id=bid["id"])


def set_posture(member, new_status):
    """Apply a posture change and its cascades; touches the member once."""
    if member["certification_status"] == new_status:
        return
    member["certification_status"] = new_status
    store.touch(member)
    if new_status in ("PROBATION", "SUSPENDED"):
        suspend_active_programs(member)
    if new_status == "SUSPENDED":
        withdraw_submitted_bids(member, "MEMBER_SUSPENDED")
