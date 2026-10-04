"""Retail store donation programs and pickup logistics."""

from decimal import Decimal, ROUND_FLOOR

import store

NETWORK_MEAL_FACTOR = Decimal("1.2")
MISSED_RUN_LIMIT = 3


def meal_equivalent(collected_lbs):
    return int((Decimal(int(collected_lbs)) / NETWORK_MEAL_FACTOR)
               .to_integral_value(rounding=ROUND_FLOOR))


def pickups_of(program_id):
    return sorted(
        [p for p in store.pickups.values() if p["program_id"] == program_id],
        key=lambda p: (p["scheduled_date"], p["created_at"], p["_seq"]),
    )


def consecutive_missed(program_id):
    """The run of MISSED pickups that ends at the most recent MISSED pickup.

    PRD 3.9 recomputes the count over the program's pickups in scheduled_date
    ascending order (created_at breaking ties) and counts "the run of MISSED
    pickups that ends at the most recent one" -- the most recent MISSED row,
    i.e. the pickup that was just marked.  Pickups still SCHEDULED for a later
    date sit after that run and do not reset it; they are swept to MISSED when
    the run reaches the threshold.
    """
    ordered = pickups_of(program_id)
    last_missed = None
    for index, pickup in enumerate(ordered):
        if pickup["pickup_status"] == "MISSED":
            last_missed = index
    if last_missed is None:
        return 0
    count = 0
    for pickup in reversed(ordered[:last_missed + 1]):
        if pickup["pickup_status"] != "MISSED":
            break
        count += 1
    return count


def mark_missed(pickup):
    pickup["pickup_status"] = "MISSED"
    store.touch(pickup)
    program = store.programs.get(pickup["program_id"])
    if program is None:
        return pickup
    if consecutive_missed(program["id"]) >= MISSED_RUN_LIMIT:
        if program["program_status"] != "SUSPENDED":
            program["program_status"] = "SUSPENDED"
            store.touch(program)
        for other in pickups_of(program["id"]):
            if other["pickup_status"] == "SCHEDULED":
                other["pickup_status"] = "MISSED"
                store.touch(other)
    return pickup
