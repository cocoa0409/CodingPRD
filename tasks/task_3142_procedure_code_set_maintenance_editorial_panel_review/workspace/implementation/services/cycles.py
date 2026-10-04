"""Release-cycle budget pools and comment-window governance.

PRD.md 2.11 / 2.8 and SCAFFOLD.yaml `release_cycle_code_pool_allocation` /
`comment_period_governance`.

Pool arithmetic (capacity `c`):
    editorial_reserved_codes = floor(c * 0.40)
    additions_pool_codes     = min(140, floor(c * 0.35))
    catiii_pool_codes        = min(25,  floor(c * 0.05))
    discretionary_codes      = c - editorial - additions - catiii
    budget_gate_status       = EXHAUSTED when discretionary_codes < 40 else OPEN

Under `single_floor_budgeting` the three unbounded percentages are summed first
and the sum is floored once, which can leave the discretionary pool one
descriptor lower for the same capacity (192 -> 40 by default, 39 single-floored).
"""

from datetime import datetime, timezone

from money import Decimal, dec, floor_int
import store

EDITORIAL_RESERVED_PCT = Decimal("0.40")
ADDITIONS_POOL_PCT = Decimal("0.35")
ADDITIONS_POOL_CAP = 140
CATIII_POOL_PCT = Decimal("0.05")
CATIII_POOL_CAP = 25
DISCRETIONARY_FLOOR = 40
MIN_COMMENT_DAYS = 30

ERRATA_DEADLINE_DEFAULT = "2027-06-30"


def _floored_pct(capacity, pct):
    return floor_int(dec(capacity) * pct)


def pool_allocation(capacity, single_floor=False):
    """Return the four pool figures for a capacity.

    Default (`per_bucket_floors`): each bucket is floored individually and the
    three are subtracted in the order editorial, additions, category III.

    `single_floor`: the three unbounded percentages are summed first and the
    sum is floored once, so the descriptors absorbed are one lower than the
    default whenever the percentages do not total a whole number (192 -> 40
    absorbed by default, 39 single-floored).
    """
    capacity = int(capacity or 0)

    if single_floor:
        combined = _floored_pct(
            capacity, EDITORIAL_RESERVED_PCT + ADDITIONS_POOL_PCT + CATIII_POOL_PCT
        )
        editorial = _floored_pct(capacity, EDITORIAL_RESERVED_PCT)
        catiii = min(CATIII_POOL_CAP, _floored_pct(capacity, CATIII_POOL_PCT))
        additions = min(ADDITIONS_POOL_CAP, combined - editorial - catiii)
    else:
        editorial = _floored_pct(capacity, EDITORIAL_RESERVED_PCT)
        additions = min(ADDITIONS_POOL_CAP, _floored_pct(capacity, ADDITIONS_POOL_PCT))
        catiii = min(CATIII_POOL_CAP, _floored_pct(capacity, CATIII_POOL_PCT))

    discretionary = capacity - editorial - additions - catiii
    return {
        "editorial_reserved_codes": editorial,
        "additions_pool_codes": additions,
        "catiii_pool_codes": catiii,
        "discretionary_codes": discretionary,
    }


def recompute_pools(cycle):
    """Recompute the four pool figures plus submission_count and the gate."""
    capacity = int(cycle.get("code_set_capacity") or 0)
    pools = pool_allocation(capacity, bool(cycle.get("single_floor_budgeting")))
    cycle.update(pools)
    cycle["submission_count"] = sum(
        1 for c in store.code_changes.values() if c.get("cycle_id") == cycle.get("id")
    )
    cycle["budget_gate_status"] = (
        "EXHAUSTED" if pools["discretionary_codes"] < DISCRETIONARY_FLOOR else "OPEN"
    )
    return cycle


def effective_date_for_year(year):
    """January 1 of year + 1 (PRD.md 3.6)."""
    return datetime(int(year) + 1, 1, 1, tzinfo=timezone.utc)


def comment_duration_days(open_at, close_at):
    """Whole-day difference between the close and open instants (PRD.md 2.8)."""
    if open_at is None or close_at is None:
        return None
    return (close_at - open_at).days


def window_acceptable(open_at, close_at):
    """Acceptable when the whole-day difference is at least 30 days."""
    days = comment_duration_days(open_at, close_at)
    if days is None:
        return False
    return days >= MIN_COMMENT_DAYS


def addendum_deadline_for_cycle(cycle):
    """The November 15 addendum close of the cycle naming this meeting."""
    if cycle is None:
        return None
    return cycle.get("addendum_comment_close")


def cycle_for_meeting(meeting_id):
    """The release cycle whose `meeting_ids` names this meeting."""
    if meeting_id is None:
        return None
    for cycle in store.release_cycles.values():
        if meeting_id in (cycle.get("meeting_ids") or []):
            return cycle
    return None