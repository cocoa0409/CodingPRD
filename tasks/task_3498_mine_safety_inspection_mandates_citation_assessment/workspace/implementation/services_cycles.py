"""Statutory inspection-cycle geometry (PRD 2.6) and quota crediting (PRD 3.2)."""
from datetime import timedelta

import store
from constants import SURFACE_CYCLE_DAYS, UNDERGROUND_CYCLE_DAYS
from errors import ApiError, ERR_CYCLE_PERIOD_INVALID


def expected_cycle_days(mine_type):
    return UNDERGROUND_CYCLE_DAYS if mine_type == "UNDERGROUND" else SURFACE_CYCLE_DAYS


def validate_geometry(mine, period_start, period_end):
    """Exact statutory window geometry; violations are ERR_CYCLE_PERIOD_INVALID.

    The span must be exactly 90 inclusive days (UNDERGROUND) or 180 inclusive
    days (SURFACE); the first cycle starts on the mine's activation_date; every
    later cycle's period_start equals the previous cycle's period_end + 1 day.
    """
    span_days = (period_end - period_start).days + 1
    if span_days != expected_cycle_days(mine["mine_type"]):
        raise ApiError(
            ERR_CYCLE_PERIOD_INVALID,
            "cycle window must span exactly {} inclusive days for a {} mine".format(
                expected_cycle_days(mine["mine_type"]), mine["mine_type"]
            ),
        )
    existing = [c for c in store.cycles.values() if c["mine_id"] == mine["id"]]
    if not existing:
        if period_start != mine["activation_date"]:
            raise ApiError(
                ERR_CYCLE_PERIOD_INVALID,
                "the first cycle must start on the mine's activation_date",
            )
    else:
        previous = max(existing, key=lambda c: c["cycle_index"])
        if period_start != previous["period_end"] + timedelta(days=1):
            raise ApiError(
                ERR_CYCLE_PERIOD_INVALID,
                "period_start must be exactly one day after the previous cycle's period_end",
            )


def credit_completion(mine_id, completed_at):
    """inspection_quota_crediting (PRD 3.2). Pinned evaluation order:

    (1) candidate set = DELINQUENT cycles of the mine still below requirement,
        ordered period_start ASC then created_at ASC; credit the FIRST only;
    (2) else credit the unique OPEN cycle whose inclusive [period_start,
        period_end] window contains the completion date;
    (3) else no credit. Crediting a DELINQUENT cycle up to its requirement
        transitions it to CURED.
    """
    mine_cycles = [c for c in store.cycles.values() if c["mine_id"] == mine_id]
    delinquent = [
        c for c in mine_cycles
        if c["status"] == "DELINQUENT" and c["completed_inspections"] < c["required_inspections"]
    ]
    delinquent.sort(key=lambda c: (c["period_start"], c["created_at"], c["_seq"]))
    target = None
    if delinquent:
        target = delinquent[0]
    else:
        completed_date = completed_at.date()
        open_hits = [
            c for c in mine_cycles
            if c["status"] == "OPEN"
            and c["period_start"] <= completed_date <= c["period_end"]
        ]
        open_hits.sort(key=lambda c: (c["period_start"], c["created_at"], c["_seq"]))
        if open_hits:
            target = open_hits[0]
    if target is None:
        return
    target["completed_inspections"] += 1
    if (
        target["status"] == "DELINQUENT"
        and target["completed_inspections"] >= target["required_inspections"]
    ):
        target["status"] = "CURED"
    store.touch(target)
