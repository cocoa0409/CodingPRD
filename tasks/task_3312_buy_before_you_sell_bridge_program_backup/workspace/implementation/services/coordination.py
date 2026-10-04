"""Coordination-task scheduling and escalation (PRD 3.7).

A task is created against a program and a referral with a ``task_kind`` and a
``due_date``, and it opens ``OPEN``.  Each task occupies a half-open interval
ending at its ``due_date`` and beginning ``TASK_SLOT_DAYS`` before it, and a new
task may not overlap any non-terminal task already scheduled for the same
referral.

The half-open convention matters at the boundary: a task that ends exactly where
another begins is **adjacent** rather than overlapping, and only a genuine
overlap is refused, with ``ERR_OVERLAPPING_TASK``.  This module implements that
literally -- intervals are compared as ``[start, end)`` and the predicate is
``a_start < b_end and b_start < a_end``, under which a zero-length touch is
never an overlap.

``TASK_SLOT_DAYS`` is deliberately left unvalued by the PRD (see
``constants.py``).  When it is ``None`` the interval degenerates to the empty
``[due_date, due_date)``, which can overlap nothing, so scheduling never refuses
spuriously; the adjacency and half-open semantics above are still in force and
take effect the moment a length is pinned.
"""

from constants import TASK_SLOT_DAYS
from services import current_time
from store import db
from timeutil import parse_iso

TERMINAL_TASK_STATUSES = ("COMPLETED", "CANCELLED")


def slot_bounds(due_date):
    """The task's half-open interval ``[start, end)`` as datetimes."""
    end = parse_iso(due_date) if isinstance(due_date, str) else due_date
    if TASK_SLOT_DAYS is None:
        return end, end
    from datetime import timedelta

    return end - timedelta(days=int(TASK_SLOT_DAYS)), end


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap.  Adjacent intervals (a_end == b_start) do not."""
    return a_start < b_end and b_start < a_end


def find_overlapping_task(referral_id, due_date, exclude_id=None):
    """The first non-terminal task for the referral whose slot overlaps."""
    start, end = slot_bounds(due_date)
    for task in db.all("coordination_tasks"):
        if task.get("referral_id") != referral_id:
            continue
        if exclude_id is not None and task.get("id") == exclude_id:
            continue
        if task.get("status") in TERMINAL_TASK_STATUSES:
            continue
        other_start, other_end = slot_bounds(task.get("due_date"))
        if _overlaps(start, end, other_start, other_end):
            return task
    return None


def escalate_overdue_tasks(program_id):
    """Move every overdue ``OPEN`` task for the program to ``IN_PROGRESS``.

    PRD 3.6: going live performs this sweep -- every coordination task belonging
    to the program that is still ``OPEN`` and whose ``due_date`` has already
    passed the logical clock is escalated in the same operation.

    A task's referral is dragged along by the change: PRD 2.5 states that a
    cascade from another resource "is still a mutation and still refreshes
    ``updated_at`` and increments ``version`` on every resource it touches", so
    each affected referral is refreshed here as well.
    """
    from services import touch

    now = current_time()
    escalated = []
    for task in db.all("coordination_tasks"):
        if task.get("bridge_program_id") != program_id:
            continue
        if task.get("status") != "OPEN":
            continue
        due = parse_iso(task.get("due_date"))
        if due is None:
            continue
        if due < now:
            task["status"] = "IN_PROGRESS"
            touch(task)
            escalated.append(task)

    for task in escalated:
        referral = db.get("referrals", task.get("referral_id"))
        if referral is not None:
            touch(referral)
    return escalated


def tasks_for_referral(referral_id):
    return [t for t in db.all("coordination_tasks") if t.get("referral_id") == referral_id]


def all_tasks_completed(referral_id):
    tasks = tasks_for_referral(referral_id)
    if not tasks:
        return True
    return all(t.get("status") == "COMPLETED" for t in tasks)


def last_open_task(referral_id, exclude_id):
    """True when completing ``exclude_id`` leaves no other open task."""
    for task in tasks_for_referral(referral_id):
        if task.get("id") == exclude_id:
            continue
        if task.get("status") in ("OPEN", "IN_PROGRESS"):
            return False
    return True


def tasks_unlocking_repair_complete(program_id):
    """Every PHOTOGRAPHY / REPAIR_BID task for the program is COMPLETED.

    PRD 3.4 gates repair disbursement on this, and the scaffold's
    ``RepairAdvance`` APPROVED->DISBURSED transition states it as a
    precondition.  With no such tasks present the gate is vacuously satisfied.
    """
    from constants import TASK_KINDS_UNLOCKING_REPAIR

    relevant = [
        t for t in db.all("coordination_tasks")
        if t.get("bridge_program_id") == program_id
        and t.get("task_kind") in TASK_KINDS_UNLOCKING_REPAIR
    ]
    if not relevant:
        return True
    return all(t.get("status") == "COMPLETED" for t in relevant)


def has_approved_repair_advance(program_id):
    return any(
        r.get("status") == "APPROVED"
        for r in db.all("repair_advances")
        if r.get("bridge_program_id") == program_id
    )


def has_completed_task_for_program(program_id):
    """Used by the approved-advance rejection compensation rule (PRD 3.4)."""
    return any(
        t.get("status") == "COMPLETED"
        for t in db.all("coordination_tasks")
        if t.get("bridge_program_id") == program_id
    )