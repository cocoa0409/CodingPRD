"""Clinical thresholds measured one unit either side of their inclusive edge.

Fifteen minutes of recovery, day forty-two of maturation, six hundred millilitres of
flow and thirty whole days of infection attribution are all boundary-inclusive, so each
scenario here holds everything else constant and moves only the quantity under test.
"""

from test_helpers import assertions
from test_helpers import canonical_instant
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success

SEDATION_END_AT = "2026-08-01T14:00:00Z"
FIRST_OBSERVED_AT = "2026-08-01T14:10:00Z"
SHORT_SPAN_OBSERVED_AT = "2026-08-01T14:24:00Z"
EXACT_SPAN_OBSERVED_AT = "2026-08-01T14:25:00Z"
DISCHARGE_CLOCK = "2026-08-01T14:30:00Z"


def _recovery_case_fourteen_minutes_apart(api):
    """A case in recovery with two qualifying observations only fourteen minutes apart.

    Both observations carry an Aldrete score of 9 on room air, so the count criterion
    and the latest-observation criteria hold from the first discharge attempt onward and
    only the span can explain a refusal.
    """
    bundle = fx.seed_case_in_recovery(api, sedation_end_at=SEDATION_END_AT)
    bundle["observations"] = [
        fx.chart_observation(api, bundle, FIRST_OBSERVED_AT, aldrete_score=9, on_room_air=True),
        fx.chart_observation(
            api, bundle, SHORT_SPAN_OBSERVED_AT, aldrete_score=9, on_room_air=True
        ),
    ]
    fx.set_clock(api, DISCHARGE_CLOCK)
    return bundle


def test_01_a_fourteen_minute_recovery_span_is_one_minute_short(api):
    """Two perfectly good observations, refused for the gap between them.

    The PRD states: "the span between the earliest and latest `observed_at` must be at
    least fifteen minutes, boundary inclusive, so a pair of observations charted exactly
    a quarter of an hour apart qualifies."

    It also states: "at least two observations must exist for the procedure; the
    observation with the greatest `observed_at`, breaking ties by `created_at` ascending,
    must have an `aldrete_score` of 9 or above **and** `on_room_air` true".

    Both of those criteria already hold here, so the refusal isolates the span alone and
    the whole discharge cascade is withheld: the referral is still SCHEDULED and the
    access still carries the DYSFUNCTIONAL status its triage wrote.

    Design: Difficulty/boundary_precision_check/recovery_observation_span_of_exactly_fifteen_minutes_is_sufficient
    """
    bundle = _recovery_case_fourteen_minutes_apart(api)

    refused = api.discharge_procedure(bundle["procedure_id"], bundle["nurse_headers"])
    validate_error(refused, "ERR_RECOVERY_CRITERIA_NOT_MET", 422)

    unchanged = fx.read_procedure(api, bundle["procedure_id"])
    assert unchanged["clinical_status"] == "RECOVERY"
    assert unchanged["discharged_at"] is None

    observations, meta = validate_paginated(
        api.list_recovery_observations(bundle["procedure_id"], fx.ADMIN)
    )
    assert meta["total_count"] == 2
    assert observations[-1]["aldrete_score"] == 9
    assert observations[-1]["on_room_air"] is True

    assert fx.read_referral(api, bundle["referral_id"])["status"] == "SCHEDULED"
    assert fx.read_access(api, bundle["access_id"])["status"] == "DYSFUNCTIONAL"


def test_02_a_third_observation_makes_the_span_exactly_fifteen_and_it_passes(api):
    """The identical discharge call succeeds once the span reaches the inclusive edge.

    The PRD states: "**Hop 2.** The parent referral moves `SCHEDULED → COMPLETED` with
    `completed_at` set to the clock."

    The added observation carries the same Aldrete score and the same room-air flag as
    the two already charted, so nothing but the fifteen-minute span has changed; the
    access then returns to `IN_USE` with an angioplasty count of 1 and the weight-two
    burden that count implies.

    Design: Difficulty/boundary_precision_check/recovery_observation_span_of_exactly_fifteen_minutes_is_sufficient
    """
    bundle = _recovery_case_fourteen_minutes_apart(api)
    validate_error(
        api.discharge_procedure(bundle["procedure_id"], bundle["nurse_headers"]),
        "ERR_RECOVERY_CRITERIA_NOT_MET",
        422,
    )

    fx.chart_observation(api, bundle, EXACT_SPAN_OBSERVED_AT, aldrete_score=9, on_room_air=True)
    observations, meta = validate_paginated(
        api.list_recovery_observations(bundle["procedure_id"], fx.ADMIN)
    )
    assert meta["total_count"] == 3
    charted = [canonical_instant(observation["observed_at"]) for observation in observations]
    assert charted == [
        FIRST_OBSERVED_AT,
        SHORT_SPAN_OBSERVED_AT,
        EXACT_SPAN_OBSERVED_AT,
    ]

    discharged = validate_success(
        api.discharge_procedure(bundle["procedure_id"], bundle["nurse_headers"])
    )
    assert discharged["clinical_status"] == "DISCHARGED"
    assertions.assert_instant_equals(discharged["discharged_at"], DISCHARGE_CLOCK, "discharged_at")

    referral = fx.read_referral(api, bundle["referral_id"])
    assert referral["status"] == "COMPLETED"
    assertions.assert_instant_equals(referral["completed_at"], DISCHARGE_CLOCK, "completed_at")

    access = fx.read_access(api, bundle["access_id"])
    assert access["status"] == "IN_USE"
    assert access["angioplasty_count"] == 1
    assert access["intervention_burden_score"] == 2
    assertions.assert_burden_score(access)


DAY_FORTY_ONE_CLOCK = "2026-07-31T12:00:00Z"
DAY_FORTY_TWO_CLOCK = "2026-08-01T00:00:00Z"


def _active_plan_one_day_short_of_maturity(api):
    """An ACTIVE catheter-to-fistula plan observed at a clock that makes the AVF 41 days old.

    The fistula was placed on 2026-06-20 and carries exactly two surveillance readings,
    so the surveillance criterion sits on its own inclusive boundary and never fails.
    """
    center = fx.seed_center(api)
    catheter = fx.seed_catheter_in_use(api, center["patient_id"], placed_on="2026-05-01")
    fistula = fx.seed_access_maturing(
        api, center["patient_id"], access_type="AVF", placed_on="2026-06-20"
    )
    readings = fx.seed_reading_pair(api, fistula["id"], center["facility_id"])
    assert len(readings) == 2

    plan = fx.seed_active_plan(api, center["patient_id"], catheter, fistula["id"])
    assert plan["status"] == "ACTIVE"
    fx.set_clock(api, DAY_FORTY_ONE_CLOCK)
    return center, catheter, fistula, plan


def test_03_day_forty_one_fails_and_day_forty_two_passes_on_the_identical_payload(api):
    """The only thing that changes between the two checks is the clock.

    The PRD states: "`days_since_placement`, the count of whole calendar days from the
    target access's `placed_on` to the clock's current calendar date, must be at least
    42; fewer days adds `MATURATION_DAYS`."

    It also states: "Measurements of exactly 6.0 millimetres diameter, exactly 600
    millilitres per minute, exactly 6.0 millimetres depth, exactly day 42 and exactly two
    readings all **pass**; 5.9, 599, 6.1, day 41 and one reading all fail."

    Because `MATURATION_DAYS` is the sole failure reason on the first check, that check
    also proves the diameter, flow, depth and surveillance criteria all pass at their own
    exact limits.

    Design: Difficulty/boundary_precision_check/maturation_day_forty_two_and_flow_six_hundred_are_inclusive_boundaries
    """
    _center, _catheter, _fistula, plan = _active_plan_one_day_short_of_maturity(api)

    short = fx.file_maturation_check(api, plan["id"], diameter_mm=6.0, flow_ml_min=600, depth_mm=6.0)
    assert short["days_since_placement"] == 41
    assert short["readiness_met"] is False
    assert short["readiness_failure_reasons"] == ["MATURATION_DAYS"]
    assert short["status"] == "MATURATION_HOLD"
    assert short["maturation_check_count"] == 1
    assertions.assert_ascii_sorted(short["readiness_failure_reasons"], "readiness_failure_reasons")

    fx.set_clock(api, DAY_FORTY_TWO_CLOCK)
    mature = fx.file_maturation_check(api, plan["id"], diameter_mm=6.0, flow_ml_min=600, depth_mm=6.0)
    assert mature["days_since_placement"] == 42
    assert mature["readiness_met"] is True
    assert mature["readiness_failure_reasons"] == []
    assert mature["status"] == "ACTIVE"
    assert mature["maturation_check_count"] == 2
    assert mature["last_diameter_mm"] == 6.0
    assert mature["last_flow_ml_min"] == 600
    assert mature["last_depth_mm"] == 6.0


def test_04_a_flow_of_five_hundred_and_ninety_nine_holds_the_plan_again(api):
    """One millilitre below the floor reopens the hold, and the counter keeps counting.

    The PRD states: "a failing check on an `ACTIVE` plan moves it
    `ACTIVE → MATURATION_HOLD`, and a passing check on a plan in `MATURATION_HOLD` moves
    it back `MATURATION_HOLD → ACTIVE` provided the target access has not yet reached
    `IN_USE`."

    It also states: "the counter counts checks, not passes, and is never reset."

    A readiness check is a measurement and nothing more: the PRD states "**Conversion** is
    not an operation a caller invokes", so the fistula stays MATURING, the catheter stays
    IN_USE and `converted_at` stays null however the readiness swings.

    Design: Difficulty/boundary_precision_check/maturation_day_forty_two_and_flow_six_hundred_are_inclusive_boundaries
    """
    _center, catheter, fistula, plan = _active_plan_one_day_short_of_maturity(api)

    fx.file_maturation_check(api, plan["id"], diameter_mm=6.0, flow_ml_min=600, depth_mm=6.0)
    fx.set_clock(api, DAY_FORTY_TWO_CLOCK)
    fx.file_maturation_check(api, plan["id"], diameter_mm=6.0, flow_ml_min=600, depth_mm=6.0)

    held = fx.file_maturation_check(api, plan["id"], diameter_mm=6.0, flow_ml_min=599, depth_mm=6.0)
    assert held["readiness_met"] is False
    assert held["readiness_failure_reasons"] == ["FLOW"]
    assert held["status"] == "MATURATION_HOLD"
    assert held["maturation_check_count"] == 3
    assert held["days_since_placement"] == 42
    assert held["last_flow_ml_min"] == 599
    assert held["last_diameter_mm"] == 6.0
    assert held["last_depth_mm"] == 6.0
    assert held["converted_at"] is None

    assert fx.read_access(api, fistula["id"])["status"] == "MATURING"
    assert fx.read_access(api, catheter["id"])["status"] == "IN_USE"


DISCHARGED_AT = "2026-08-01T10:00:00Z"
DAY_THIRTY_ONSET = "2026-08-31T10:00:00Z"
DAY_THIRTY_ONE_ONSET = "2026-09-01T10:00:01Z"
SURVEILLANCE_CLOCK = "2026-09-02T00:00:00Z"


def _case_discharged_at_exactly_ten(api):
    """An angioplasty discharged at 2026-08-01T10:00:00Z, the anchor of the window."""
    bundle = fx.seed_scheduled_case(
        api,
        scheduled_start="2026-08-01T08:00:00Z",
        scheduled_end="2026-08-01T09:00:00Z",
        sedation_level="MODERATE",
    )
    fx.set_clock(api, "2026-08-01T08:00:00Z")
    fx.start_case(api, bundle)
    fx.move_to_recovery(api, bundle, "2026-08-01T09:30:00Z")
    fx.set_clock(api, DISCHARGED_AT)
    fx.chart_observation(api, bundle, "2026-08-01T09:40:00Z", aldrete_score=8, on_room_air=False)
    fx.chart_observation(api, bundle, "2026-08-01T09:55:00Z", aldrete_score=9, on_room_air=True)
    bundle["procedure"] = fx.discharge(api, bundle)
    assertions.assert_instant_equals(
        bundle["procedure"]["discharged_at"], DISCHARGED_AT, "discharged_at"
    )

    access = fx.read_access(api, bundle["access_id"])
    assert access["status"] == "IN_USE"
    assert access["angioplasty_count"] == 1
    assert access["intervention_burden_score"] == 2

    fx.set_clock(api, SURVEILLANCE_CLOCK)
    return bundle


def test_05_day_thirty_is_attributable_and_one_second_past_thirty_one_is_not(api):
    """The floored day count decides, and it is measured in whole elapsed days.

    The PRD states: "The event's `days_post_procedure` is the whole number of days
    between `discharged_at` and `onset_at`, computed as the elapsed seconds between the
    two instants divided by 86400 and floored — so 29 days and 23 hours is 29, not 30."

    It also states: "`attributable` is true when `days_post_procedure` is between 0 and
    30 inclusive and false otherwise: exactly 30 days is attributable, 31 is not, and an
    `onset_at` before `discharged_at` yields a negative count and is not attributable."

    The first onset is exactly 2592000 seconds after the discharge and the second is
    2678401 seconds after it, one second past the thirty-first whole day, so the two
    events straddle the edge with the same anchor.

    Design: Difficulty/boundary_precision_check/infection_attribution_window_is_thirty_whole_days_inclusive
    """
    bundle = _case_discharged_at_exactly_ten(api)

    inside = fx.record_infection(
        api, bundle["procedure_id"], DAY_THIRTY_ONSET, event_type="ACCESS_SITE_INFECTION"
    )
    assert inside["days_post_procedure"] == 30
    assert inside["attributable"] is True
    assert inside["access_id"] == bundle["access_id"]
    assertions.assert_infection_event(inside)

    outside = fx.record_infection(
        api,
        bundle["procedure_id"],
        DAY_THIRTY_ONE_ONSET,
        event_type="BACTEREMIA",
        organism="Staphylococcus epidermidis",
    )
    assert outside["days_post_procedure"] == 31
    assert outside["attributable"] is False
    assert outside["access_id"] == bundle["access_id"]
    assertions.assert_infection_event(outside)


def test_06_only_the_attributable_event_moves_the_access(api):
    """The boundary is observable on a second entity: the burden score.

    The PRD states: "When and only when an event is attributable, the access's
    `attributable_infection_count` increments by one and its `intervention_burden_score`
    is recomputed with the weight of five per attributable infection, which can push an
    access over the burden threshold that makes conversion indicated."

    It also states: "A non-attributable event is still persisted in full — it simply
    touches neither counter nor status."

    So the burden is 7 — two for the single angioplasty plus five for the single
    attributable infection — and the access stays IN_USE because the PRD moves it only
    "once the access's `attributable_infection_count` reaches 2 or more".

    Design: Difficulty/boundary_precision_check/infection_attribution_window_is_thirty_whole_days_inclusive
    """
    bundle = _case_discharged_at_exactly_ten(api)

    fx.record_infection(api, bundle["procedure_id"], DAY_THIRTY_ONSET)
    fx.record_infection(
        api,
        bundle["procedure_id"],
        DAY_THIRTY_ONE_ONSET,
        event_type="BACTEREMIA",
        organism="Staphylococcus epidermidis",
    )

    access = fx.read_access(api, bundle["access_id"])
    assert access["attributable_infection_count"] == 1
    assert access["angioplasty_count"] == 1
    assert access["intervention_burden_score"] == 7
    assert access["status"] == "IN_USE"
    assertions.assert_burden_score(access)

    attributable, attributable_meta = validate_paginated(
        api.list_infection_events(
            fx.ADMIN, {"access_id": bundle["access_id"], "attributable": "true"}
        )
    )
    assert attributable_meta["total_count"] == 1
    assert attributable[0]["days_post_procedure"] == 30

    events, meta = validate_paginated(
        api.list_infection_events(fx.ADMIN, {"access_id": bundle["access_id"]})
    )
    assert meta["total_count"] == 2
    assert [canonical_instant(event["onset_at"]) for event in events] == [
        DAY_THIRTY_ONSET,
        DAY_THIRTY_ONE_ONSET,
    ]
    assert [event["attributable"] for event in events] == [True, False]
