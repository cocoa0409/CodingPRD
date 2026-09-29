"""Booking arithmetic: room occupancy, the nurse ceiling, recovery bays and surge.

Three resources are checked against three different interval conventions, and the
capacity headrooms are evaluated in a pinned order, so each scenario here isolates
one dimension and proves the others were not the reason for the outcome.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

BENIGN_READING_AT = "2026-07-31T09:00:00Z"


def _routine_referrals(api, center, access_id, count):
    """`count` TRIAGED referrals on one access, every one of them ROUTINE.

    The single benign reading of flow 900, venous pressure 120 and recirculation 5.0
    scores 0, so no scheduling-date window is ever enforced on these bookings.
    """
    fx.seed_reading(
        api,
        access_id,
        center["facility_id"],
        BENIGN_READING_AT,
        access_flow_ml_min=900,
        venous_pressure_mmhg=120,
        recirculation_pct=5.0,
    )
    referrals = []
    for _ in range(count):
        referral = fx.seed_referral(
            api, access_id, center["facility_id"], missed_treatment_count=0
        )
        triaged = fx.triage(api, referral["id"])
        assert triaged["triage_score"] == 0
        assert triaged["urgency"] == "ROUTINE"
        referrals.append(triaged)
    return referrals


def _buffered_room_setup(api):
    """Room with the default 30-minute turnover and one case booked 13:00-14:00."""
    center = fx.seed_center(api)
    room = fx.seed_room(api, turnover_buffer_min=30, daily_case_cap=6, recovery_bay_count=3)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    referral_a, referral_b, referral_c = _routine_referrals(api, center, access["id"], 3)
    incumbent = fx.book_case(
        api,
        referral_a["id"],
        room["id"],
        center["operator_id"],
        referral_a["version"],
        "2026-08-01T13:00:00Z",
        "2026-08-01T14:00:00Z",
    )
    return center, room, incumbent, referral_b, referral_c


def _attempt(api, referral, room, center, start, end, **overrides):
    return api.create_procedure(
        {
            "referral_id": referral["id"],
            "room_id": room["id"],
            "primary_operator_id": center["operator_id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "NONE",
            "scheduled_start": start,
            "scheduled_end": end,
            "expected_referral_version": referral["version"],
            **overrides,
        },
        fx.COORDINATOR,
    )


def test_01_the_turnover_buffer_extends_both_sides_of_a_room_comparison(api):
    """A fifteen-minute clinical gap still collides, and so does a candidate that ends on the hour.

    The PRD states: "Room occupancy is checked next, and it is a **pairwise** rule
    that includes the room's turnover buffer on both sides."

    It also states: "The candidate's occupied span runs from its `scheduled_start` up
    to but not including its `scheduled_end` plus the room's `turnover_buffer_min`."

    The incumbent occupies [13:00, 14:30). The 14:15 candidate occupies
    [14:15, 15:45) and intersects it even though the raw clinical intervals do not
    touch; the 12:00 candidate occupies [12:00, 13:30) and reaches into the
    incumbent's start, which an implementation that buffers only the incumbent would
    wrongly accept.

    Design: Difficulty/resource_temporal_overlap/room_occupancy_is_pairwise_and_the_turnover_buffer_extends_both_intervals
    """
    center, room, _incumbent, referral_b, _referral_c = _buffered_room_setup(api)

    late_overlap = _attempt(
        api, referral_b, room, center, "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z"
    )
    validate_error(late_overlap, "ERR_ROOM_OCCUPIED", 409)

    early_overlap = _attempt(
        api, referral_b, room, center, "2026-08-01T12:00:00Z", "2026-08-01T13:00:00Z"
    )
    validate_error(early_overlap, "ERR_ROOM_OCCUPIED", 409)

    # Neither rejection consumed the referral, so the version it declared is still current.
    untouched = fx.read_referral(api, referral_b["id"])
    assert untouched["status"] == "TRIAGED"
    assert untouched["version"] == referral_b["version"]

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 1


def test_02_exact_adjacency_after_the_buffer_is_legal_and_so_is_a_disjoint_slot(api):
    """The buffered spans are half-open, so a case may start the minute turnover ends.

    The PRD states: "Because the upper endpoint is excluded, adjacency is legal
    exactly when the candidate's `scheduled_start` is at or after the existing
    booking's `scheduled_end` plus the turnover buffer — a case may begin at the very
    minute the previous case's turnover completes, but not one minute earlier."

    The PRD also states: "A candidate whose `sedation_level` is `NONE` skips the nurse
    ceiling and the bay check entirely — both are treated as unlimited — but it still
    consumes room headroom and still participates in room-occupancy arithmetic."

    Design: Difficulty/resource_temporal_overlap/room_occupancy_is_pairwise_and_the_turnover_buffer_extends_both_intervals
    """
    center, room, _incumbent, referral_b, referral_c = _buffered_room_setup(api)

    validate_error(
        _attempt(api, referral_b, room, center, "2026-08-01T14:15:00Z", "2026-08-01T15:15:00Z"),
        "ERR_ROOM_OCCUPIED",
        409,
    )

    adjacent = _attempt(
        api, referral_b, room, center, "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z"
    )
    booked_b = validate_success(adjacent, 201)
    assert booked_b["clinical_status"] == "SCHEDULED"
    assert booked_b["room_id"] == room["id"]

    # [11:30, 13:00) is disjoint from both [13:00, 14:30) and [14:30, 16:00).
    disjoint = _attempt(
        api, referral_c, room, center, "2026-08-01T11:30:00Z", "2026-08-01T12:30:00Z"
    )
    booked_c = validate_success(disjoint, 201)
    assert booked_c["clinical_status"] == "SCHEDULED"

    assert fx.read_referral(api, referral_b["id"])["status"] == "SCHEDULED"
    assert fx.read_referral(api, referral_c["id"])["status"] == "SCHEDULED"

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 3


def _moderate_attempt(api, referral, room_id, center, start, end, rn_id=None):
    return api.create_procedure(
        {
            "referral_id": referral["id"],
            "room_id": room_id,
            "primary_operator_id": center["operator_id"],
            "sedation_rn_id": rn_id or center["nurse_id"],
            "procedure_type": "ANGIOPLASTY",
            "sedation_level": "MODERATE",
            "scheduled_start": start,
            "scheduled_end": end,
            "expected_referral_version": referral["version"],
        },
        fx.COORDINATOR,
    )


def _three_room_sedation_setup(api):
    """One nurse with a ceiling of two, three unbuffered rooms, two overlapping cases."""
    center = fx.seed_center(api)
    rooms = [
        fx.seed_room(api, turnover_buffer_min=0, daily_case_cap=6, recovery_bay_count=3)
        for _ in range(3)
    ]
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    referrals = _routine_referrals(api, center, access["id"], 3)

    first = validate_success(
        _moderate_attempt(
            api, referrals[0], rooms[0]["id"], center,
            "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        ),
        201,
    )
    # The second case overlaps the first on the same nurse and is still accepted,
    # which is what makes this an aggregate ceiling rather than a pairwise exclusion.
    second = validate_success(
        _moderate_attempt(
            api, referrals[1], rooms[1]["id"], center,
            "2026-08-01T13:30:00Z", "2026-08-01T14:30:00Z",
        ),
        201,
    )
    return center, rooms, referrals, first, second


def test_03_the_nurse_ceiling_tolerates_one_overlap_and_refuses_the_second(api):
    """Two concurrent sedations are legal; the third crosses the stored ceiling.

    The PRD states: "This is an aggregate-cardinality rule rather than a pairwise
    exclusion: overlapping cases on the same nurse are perfectly legal right up until
    the ceiling is reached, and the count must remain strictly below the ceiling for
    the booking to proceed."

    The 13:45-14:15 candidate intersects both incumbents, so the count reaches the
    ceiling of two and the headroom is zero. Nothing else is short: the candidate's
    room holds no bookings at all, so its room headroom is 6 and its bay headroom 3.

    Design: Difficulty/resource_temporal_overlap/sedation_rn_ceiling_is_an_aggregate_of_two_not_a_pairwise_exclusion
    """
    center, rooms, referrals, first, second = _three_room_sedation_setup(api)
    assert first["sedation_level"] == "MODERATE"
    assert second["clinical_status"] == "SCHEDULED"

    refused = _moderate_attempt(
        api, referrals[2], rooms[2]["id"], center,
        "2026-08-01T13:45:00Z", "2026-08-01T14:15:00Z",
    )
    validate_error(refused, "ERR_SEDATION_CAPACITY_EXCEEDED", 409)

    _items, empty_room = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": rooms[2]["id"]})
    )
    assert empty_room["total_count"] == 0

    untouched = fx.read_referral(api, referrals[2]["id"])
    assert untouched["status"] == "TRIAGED"
    assert untouched["version"] == referrals[2]["version"]


def test_04_the_nurse_spans_are_half_open_so_a_case_may_start_as_another_ends(api):
    """Moving the candidate fifteen minutes later drops the count to one and it books.

    The PRD states: "It counts the moderate-sedation procedures assigned to the same
    `sedation_rn_id` whose `clinical_status` is `SCHEDULED`, `IN_ROOM` or `RECOVERY`
    and whose booked span — from `scheduled_start` up to but not including
    `scheduled_end`, with no turnover buffer — intersects the candidate's identically
    constructed span."

    [14:00, 15:00) does not intersect the first case's [13:00, 14:00), so only the
    second case counts and the headroom is one. The ceiling itself is recomputed per
    request rather than stored as a running total.

    Design: Difficulty/resource_temporal_overlap/sedation_rn_ceiling_is_an_aggregate_of_two_not_a_pairwise_exclusion
    """
    center, rooms, referrals, _first, _second = _three_room_sedation_setup(api)

    validate_error(
        _moderate_attempt(
            api, referrals[2], rooms[2]["id"], center,
            "2026-08-01T13:45:00Z", "2026-08-01T14:15:00Z",
        ),
        "ERR_SEDATION_CAPACITY_EXCEEDED",
        409,
    )

    accepted = validate_success(
        _moderate_attempt(
            api, referrals[2], rooms[2]["id"], center,
            "2026-08-01T14:00:00Z", "2026-08-01T15:00:00Z",
        ),
        201,
    )
    assert accepted["clinical_status"] == "SCHEDULED"
    assert accepted["sedation_rn_id"] == center["nurse_id"]

    for room in rooms:
        _items, meta = validate_paginated(
            api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
        )
        assert meta["total_count"] == 1

    nurse = validate_success(api.get_clinician(center["nurse_id"], fx.ADMIN))
    assert nurse["max_concurrent_sedation_cases"] == 2

    _items, per_referral = validate_paginated(
        api.list_procedures(fx.ADMIN, {"referral_id": referrals[2]["id"]})
    )
    assert per_referral["total_count"] == 1
    assert fx.read_referral(api, referrals[2]["id"])["status"] == "SCHEDULED"


def _single_bay_room_setup(api):
    """A one-bay room whose only case projects the closed recovery window [14:00, 15:30]."""
    center = fx.seed_center(api)
    room = fx.seed_room(api, turnover_buffer_min=0, daily_case_cap=6, recovery_bay_count=1)
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    referrals = _routine_referrals(api, center, access["id"], 3)
    incumbent = validate_success(
        _moderate_attempt(
            api, referrals[0], room["id"], center,
            "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        ),
        201,
    )
    return center, room, referrals, incumbent


def test_05_recovery_windows_are_closed_so_touching_at_a_single_instant_collides(api):
    """Two recovery windows that meet exactly at 15:30 are treated as a collision.

    The PRD states: "Each moderate-sedation case projects a recovery window running
    from its `scheduled_end` to ninety minutes after its `scheduled_end`, and that
    window is **fully closed** — both endpoints inclusive."

    It also states: "because both endpoints are inclusive, two cases whose windows
    merely *touch* at a single instant do collide."

    Every earlier gate passed: with no turnover buffer the room span [14:30, 15:30) is
    disjoint from [13:00, 14:00), the room headroom is 6 - 1 = 5, and the nurse
    headroom is 2 - 0 = 2 because the clinical intervals do not overlap either. Only
    the closed bay windows [15:30, 17:00] and [14:00, 15:30] intersect.

    Design: Difficulty/resource_temporal_overlap/recovery_bay_windows_are_closed_so_touching_at_a_single_instant_collides
    """
    center, room, referrals, _incumbent = _single_bay_room_setup(api)

    touching = _moderate_attempt(
        api, referrals[1], room["id"], center,
        "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z",
    )
    validate_error(touching, "ERR_RECOVERY_BAY_UNAVAILABLE", 409)

    untouched = fx.read_referral(api, referrals[1]["id"])
    assert untouched["status"] == "TRIAGED"
    assert untouched["version"] == referrals[1]["version"]
    assert validate_success(api.get_procedure_room(room["id"], fx.ADMIN))["recovery_bay_count"] == 1

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 1


def test_06_one_minute_of_separation_frees_the_bay_and_the_check_reads_live_bookings(api):
    """A single minute is the whole difference, and the next collision is against the new case.

    The PRD states: "Bay headroom is the room's `recovery_bay_count` divided by one bay
    per case, taken to its floor, minus that count, and the count must remain strictly
    below the bay count."

    Shifting the candidate to 14:31 puts its window at [15:31, 17:01], disjoint from
    [14:00, 15:30] by one minute, and it books. The 16:01 candidate then projects
    [17:01, 18:31], which touches the window of the case just accepted, so the check is
    reading live bookings rather than a snapshot; 16:02 clears it, and a room with one
    bay ends the day holding three scheduled cases.

    Design: Difficulty/resource_temporal_overlap/recovery_bay_windows_are_closed_so_touching_at_a_single_instant_collides
    """
    center, room, referrals, _incumbent = _single_bay_room_setup(api)

    validate_error(
        _moderate_attempt(
            api, referrals[1], room["id"], center,
            "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z",
        ),
        "ERR_RECOVERY_BAY_UNAVAILABLE",
        409,
    )
    second = validate_success(
        _moderate_attempt(
            api, referrals[1], room["id"], center,
            "2026-08-01T14:31:00Z", "2026-08-01T15:31:00Z",
        ),
        201,
    )
    assert second["clinical_status"] == "SCHEDULED"

    validate_error(
        _moderate_attempt(
            api, referrals[2], room["id"], center,
            "2026-08-01T16:01:00Z", "2026-08-01T17:01:00Z",
        ),
        "ERR_RECOVERY_BAY_UNAVAILABLE",
        409,
    )
    third = validate_success(
        _moderate_attempt(
            api, referrals[2], room["id"], center,
            "2026-08-01T16:02:00Z", "2026-08-01T17:02:00Z",
        ),
        201,
    )
    assert third["clinical_status"] == "SCHEDULED"

    items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 3
    assert all(item["clinical_status"] == "SCHEDULED" for item in items)


def _same_day_referrals(api, center, access_id, count):
    """`count` TRIAGED referrals scoring 79, i.e. SAME_DAY, on one declining access."""
    fx.seed_reading(
        api,
        access_id,
        center["facility_id"],
        "2026-07-20T08:00:00Z",
        access_flow_ml_min=1000,
        venous_pressure_mmhg=120,
        recirculation_pct=4.0,
    )
    fx.seed_reading(
        api,
        access_id,
        center["facility_id"],
        "2026-07-28T08:00:00Z",
        access_flow_ml_min=700,
        venous_pressure_mmhg=160,
        recirculation_pct=12.0,
    )
    referrals = []
    for _ in range(count):
        referral = fx.seed_referral(
            api, access_id, center["facility_id"], missed_treatment_count=1
        )
        triaged = fx.triage(api, referral["id"])
        assert triaged["triage_score"] == 79
        assert triaged["urgency"] == "SAME_DAY"
        referrals.append(triaged)
    return referrals


def _capped_angio_suite_setup(api):
    """An ANGIO_SUITE whose daily cap of one is already spent by a 13:00 case."""
    center = fx.seed_center(api)
    room = fx.seed_room(
        api,
        room_type="ANGIO_SUITE",
        turnover_buffer_min=0,
        daily_case_cap=1,
        recovery_bay_count=3,
    )
    access = fx.seed_access_in_use(api, center["patient_id"], access_type="AVG")
    referrals = _same_day_referrals(api, center, access["id"], 3)
    incumbent = validate_success(
        _moderate_attempt(
            api, referrals[0], room["id"], center,
            "2026-08-01T13:00:00Z", "2026-08-01T14:00:00Z",
        ),
        201,
    )
    return center, room, referrals, incumbent


def test_07_the_surge_allowance_is_withheld_at_exactly_fifteen_hundred_hours(api):
    """A 15:30 start earns no surge, so the spent daily cap refuses the booking.

    The PRD states: "The surge allowance is exactly one extra case, and it is granted
    only when all three of the following hold: the referral's `urgency` is `SAME_DAY`,
    the room's `room_type` is `ANGIO_SUITE`, and the candidate's `scheduled_start`
    falls at a UTC hour strictly before 15 — that is, at or before 14:59 UTC."

    Two of the three conditions hold here, which is not enough: the room headroom is
    1 + 0 - 1 = 0. The nurse headroom is 2 and the bay headroom 3, so the room is the
    only dimension found wanting and its identifier is the one reported.

    Design: Difficulty/combinatorial_formula/sedation_capacity_nested_min_max_with_hour_gated_surge_term
    """
    center, room, referrals, _incumbent = _capped_angio_suite_setup(api)

    refused = _moderate_attempt(
        api, referrals[1], room["id"], center,
        "2026-08-01T15:30:00Z", "2026-08-01T16:30:00Z",
    )
    validate_error(refused, "ERR_ROOM_DAILY_CAP_REACHED", 409)

    untouched = fx.read_referral(api, referrals[1]["id"])
    assert untouched["status"] == "TRIAGED"
    assert untouched["version"] == referrals[1]["version"]

    facility = fx.read_facility(api, center["facility_id"])
    assert facility["referral_volume_window"] == 3
    assert facility["raw_missed_count_window"] == 3
    assert facility["partnership_score"] == 88
    assert facility["contract_status"] == "ACTIVE"


def test_08_a_surge_case_at_half_past_fourteen_runs_a_second_case_over_the_cap(api):
    """The same room, one hour earlier: the surge term lifts the headroom back to one.

    The PRD states: "Three capacity headrooms are then evaluated **in a fixed order**:
    the room's daily case cap first, then the sedation nurse's concurrency ceiling,
    then recovery-bay availability."

    The candidate's own bay window [15:30, 17:00] touches the incumbent's
    [14:00, 15:30], but with three bays the count of one still leaves a headroom of
    two, so the touching windows do not refuse this booking — the room ends the day
    holding two cases against a daily case cap of one.

    Design: Difficulty/combinatorial_formula/sedation_capacity_nested_min_max_with_hour_gated_surge_term
    """
    center, room, referrals, _incumbent = _capped_angio_suite_setup(api)

    surged = validate_success(
        _moderate_attempt(
            api, referrals[2], room["id"], center,
            "2026-08-01T14:30:00Z", "2026-08-01T15:30:00Z",
        ),
        201,
    )
    assert surged["clinical_status"] == "SCHEDULED"
    assert surged["room_id"] == room["id"]
    assert fx.read_referral(api, referrals[2]["id"])["status"] == "SCHEDULED"

    _items, meta = validate_paginated(
        api.list_procedures(fx.ADMIN, {"room_id": room["id"]})
    )
    assert meta["total_count"] == 2
    assert validate_success(api.get_procedure_room(room["id"], fx.ADMIN))["daily_case_cap"] == 1
