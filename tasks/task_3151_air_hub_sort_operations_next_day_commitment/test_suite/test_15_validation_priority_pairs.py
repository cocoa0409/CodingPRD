"""Which of two simultaneously violated rules is reported first."""
import pytest

from test_helpers import (
    TEST_USERS as H,
    api_client as api,
    confirm,
    create_package,
    create_aircraft,
    create_bank,
    create_lane,
    declare_contingency,
    depart_and_land,
    get_aircraft,
    get_package,
    ground_stop,
    induct,
    primary_sort,
    set_clock,
    setup_night,
    setup_six_lane_night,
)

CLOCK_1601_INSTANT = "2026-09-02T06:01:00Z"
CLOCK_1414 = "2026-09-01T23:34:00Z"


def test_a_lapsed_certificate_beats_a_capability_mismatch():
    """PRD §2.8: "Only after existence is settled do business rules run, in this order:
    business safety rules (`ERR_HAZMAT_CAP_EXCEEDED`, then
    `ERR_POSTURE_BLOCKS_INDUCTION`), business-temporal rules
    (`ERR_LANE_CERTIFICATION_LAPSED`), business constraints
    (`ERR_LANE_NOT_AVAILABLE`, then `ERR_BUILDUP_UNDER_CAPACITY`), fiscal capacity
    rules (`ERR_LOAD_WEIGHT_EXCEEDED`, `ERR_FEEDER_OVER_CAPACITY`,
    `ERR_FEEDER_WINDOW_CONFLICT`), then state admissibility with its large family
    of state and posture errors — whose generic member, raised when a resource is
    simply not in a state that admits the requested transition, is
    `ERR_INVALID_STATE` — and finally optimistic concurrency
    (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_lane_certification_beats_wrong_commodity_capability
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1601_INSTANT)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-PP-0001",
                             commodity_class="PERISHABLE", planned_weight_grams=20000,
                             dimension_weight_grams=20000)
    induct(package["id"])

    attempt = api.primary_sort(package["id"], {"lane_id": night["lane_hz1_id"]},
                               H["sort_operator_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_LANE_CERTIFICATION_LAPSED"


def test_the_capability_conflict_is_shadowed_by_the_temporal_rule():
    """PRD §3.3: "strict certification means the current minute is strictly before the
    lane's `certified_until_minutes`, and a lapsed certificate is refused with
    `ERR_LANE_CERTIFICATION_LAPSED`."

    Design: Difficulty/priority_pair_validation_conflict/lapsed_lane_certification_beats_wrong_commodity_capability
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1601_INSTANT)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-PP-0002",
                             commodity_class="PERISHABLE", planned_weight_grams=20000,
                             dimension_weight_grams=20000)
    induct(package["id"])

    attempt = api.primary_sort(package["id"], {"lane_id": night["lane_hz1_id"]},
                               H["sort_operator_headers"])
    assert attempt.json()["data"]["error_id"] != "ERR_LANE_NOT_AVAILABLE", (
        "the priority-8 capability conflict is shadowed"
    )


def test_the_package_stays_unsorted_after_the_priority_seven_refusal():
    """PRD §3.3: "A closed lane, or one whose capability does not match the package's commodity
    class, is refused with `ERR_LANE_NOT_AVAILABLE`;"

    Design: Difficulty/priority_pair_validation_conflict/lapsed_lane_certification_beats_wrong_commodity_capability
    """
    night = setup_six_lane_night()
    set_clock(CLOCK_1601_INSTANT)
    package = create_package(night["hub_id"], night["ac1_id"], tracking_number="1Z-PP-0003",
                             commodity_class="PERISHABLE", planned_weight_grams=20000,
                             dimension_weight_grams=20000)
    induct(package["id"])
    api.primary_sort(package["id"], {"lane_id": night["lane_hz1_id"]},
                     H["sort_operator_headers"])

    read = get_package(package["id"])
    assert read["sort_status"] == "UNSORTED"
    assert read["assigned_lane_id"] is None


def test_the_posture_block_beats_the_aircraft_state_conflict():
    """PRD §2.8: "business safety rules (`ERR_HAZMAT_CAP_EXCEEDED`, then
    `ERR_POSTURE_BLOCKS_INDUCTION`)".
    PRD §2.8: "then state admissibility with its large family of state and posture errors —
    whose generic member, raised when a resource is simply not in a state that
    admits the requested transition, is `ERR_INVALID_STATE` — and finally
    optimistic concurrency (`ERR_STALE_VERSION`)."

    Design: Difficulty/priority_pair_validation_conflict/posture_safety_block_beats_aircraft_state_conflict
    """
    night = setup_night()
    set_clock(CLOCK_1414)
    # A second aircraft on the same bank that has landed but was never unloaded.
    second = create_aircraft(night["bank_id"], tail_number="N706UP",
                             origin_station_code="MIA", scheduled_arrival_minutes=1402)
    depart_and_land(second["id"], 40000)
    package = create_package(night["hub_id"], second["id"], tracking_number="1Z-PP-0004",
                             planned_weight_grams=20000, dimension_weight_grams=20000)

    declare_contingency(night["hub_id"])
    stopped = ground_stop(night["hub_id"])
    assert stopped["posture"] == "GROUND_STOP"

    attempt = api.induct_package(package["id"], {"dimension_weight_grams": 20000},
                                 H["sort_operator_headers"])
    assert attempt.status_code == 409, attempt.text
    assert attempt.json()["data"]["error_id"] == "ERR_POSTURE_BLOCKS_INDUCTION"


def test_the_state_precondition_is_shadowed_and_the_package_is_untouched():
    """PRD §3.4: "From that instant the ordinary induction and load paths close:
    `LOCKDOWN` blocks induction, loading, departure and landing with
    `ERR_POSTURE_BLOCKS_INDUCTION`."

    Design: Difficulty/priority_pair_validation_conflict/posture_safety_block_beats_aircraft_state_conflict
    """
    night = setup_night()
    set_clock(CLOCK_1414)
    second = create_aircraft(night["bank_id"], tail_number="N707UP",
                             origin_station_code="SEA", scheduled_arrival_minutes=1402)
    depart_and_land(second["id"], 40000)
    package = create_package(night["hub_id"], second["id"], tracking_number="1Z-PP-0005",
                             planned_weight_grams=20000, dimension_weight_grams=20000)
    declare_contingency(night["hub_id"])
    ground_stop(night["hub_id"])

    attempt = api.induct_package(package["id"], {"dimension_weight_grams": 20000},
                                 H["sort_operator_headers"])
    assert attempt.json()["data"]["error_id"] != "ERR_INVALID_STATE", (
        "the priority-11 aircraft-not-UNLOADED conflict is shadowed"
    )
    assert get_aircraft(second["id"])["status"] == "LANDED", (
        "the state precondition is genuinely violated too"
    )
    read = get_package(package["id"])
    assert read["induction_status"] == "NOT_INDUCTED"
    assert read["rated_weight_grams"] is None