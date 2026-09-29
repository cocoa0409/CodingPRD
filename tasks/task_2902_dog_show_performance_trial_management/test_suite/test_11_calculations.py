"""Derived figures: fees, ring geometry, heat indices, run scores, points and titles."""

import pytest

from test_helpers import api_client, validate_success
from test_helpers.assertions import (
    assert_entry,
    assert_instant_equals,
    assert_performance_run,
    assert_ring_block,
)
from test_helpers.factories import (
    adjudicate_filing_payload,
    complete_class_payload,
    create_entry_payload,
    create_performance_run_payload,
    create_protest_payload,
    create_ring_block_payload,
    temperature_reading_payload,
)
from test_helpers.fixtures import (
    RO_HEADERS,
    SS_HEADERS,
    apply_for_show,
    approve_show,
    attach_judge,
    check_in,
    close_entries,
    close_show,
    complete_class,
    confirm_entry,
    confirmed_slot,
    enter_dog,
    measure_dog,
    offer_class,
    open_day,
    plan_ring_block,
    publish_ring_block,
    raise_filing,
    read_class,
    read_dog,
    read_entry,
    read_ring_block,
    read_show,
    read_show_version,
    register_club,
    register_judge,
    set_clock,
    setup_class_ready_to_judge,
    setup_completed_class,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import make_handler_headers, make_judge_headers


def test_the_second_entry_of_one_dog_reuses_its_armband_and_takes_the_repeat_discount():
    """One armband per dog per show, and the second entry is no longer the dog's first.

    PRD 3.5: "Armbands are per dog, per show: if any entry of this same dog at this
    same show already carries an `armband_number`, the confirming entry inherits the
    lowest such number and the show's `armband_high_water` is left alone."

    PRD 3.5: "Step six builds a single discount percentage additively from two
    independent conditions: fifteen percent when the same-dog rank is 2 or higher,
    meaning this is not the dog's first counted entry at the show, plus ten percent
    when the handler-counted set holds at least three entries."

    Design: Corner/calculations/armband_is_reused_when_the_same_dog_is_confirmed_in_a_second_class
    """
    context = setup_show_with_class(num_dogs=1, confirm_entries=True)
    show, handler, dog = context["show"], context["handler"], context["dogs"][0]
    second_class = attach_judge(
        offer_class(show, class_code="B2"), context["slot"]
    )
    repeat = enter_dog(show, second_class, dog, handler)

    confirmed = validate_success(api_client.confirm_entry(repeat["id"], SS_HEADERS), 200)
    assert_entry(confirmed)
    assert confirmed["entry_status"] == "CONFIRMED"
    assert confirmed["armband_number"] == 1
    assert confirmed["entry_fee_cents"] == 3199
    assert confirmed["levy_cents"] == 263
    assert confirmed["net_fee_cents"] == 3199
    assert confirmed["fee_basis"] == "PROVISIONAL"

    refreshed = read_show(show)
    assert refreshed["armband_high_water"] == 1
    assert refreshed["confirmed_entry_count"] == 2
    assert refreshed["fee_charged_cents"] == 7862
    assert refreshed["levy_total_cents"] == 526
    assert refreshed["fee_collected_cents"] == 7862


def test_a_received_entry_buys_its_class_no_ring_time():
    """Only the confirmed population sizes a block.

    PRD 3.6: "First the block's `scheduled_dog_count` is counted as the entries of its
    class whose `entry_status` is `CONFIRMED`, `CHECKED_IN` or `JUDGED`."

    Design: Corner/calculations/ring_block_duration_counts_confirmed_entries_and_ignores_received_ones
    """
    context = setup_show_with_class(num_dogs=2)
    show, klass, slot = context["show"], context["klass"], context["slot"]
    confirm_entry(context["entries"][0])

    block = validate_success(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], klass["id"], slot["id"], read_show_version(show),
                ring_number=1, block_start_at="2026-09-12T09:00:00Z",
            ),
            SS_HEADERS,
        ),
        201,
    )
    assert_ring_block(block)
    assert block["block_status"] == "PLANNED"
    assert block["scheduled_dog_count"] == 1
    assert block["conflict_free_minutes"] == 3
    assert block["judging_minutes_estimate"] == 3
    assert_instant_equals(block["block_end_at"], "2026-09-12T09:03:00Z", "block_end_at")
    assert block["deferred_dog_count"] == 0
    assert block["superseded_block_id"] is None


def test_a_performance_entry_prices_off_the_performance_base_and_its_own_levy():
    """The class level moves the base, and the levy is a percentage of that base.

    PRD 3.5: "Step one sets the base at 2,800 cents for a class whose `class_level` is
    `PERFORMANCE` and 3,500 cents for every other level."

    PRD 3.5: "Step four computes the catalogue levy as seven and a half percent of the
    base, rounded half-up to a whole cent — 263 cents on a 3,500-cent base and 210
    cents on a 2,800-cent base — and this rounded value is what lands in the entry's
    `levy_cents`."

    Design: Corner/calculations/performance_entry_uses_the_performance_base_fee_and_its_own_rounded_levy
    """
    context = setup_show_with_class(
        num_dogs=1, class_level="PERFORMANCE", discipline="OBEDIENCE",
        show_overrides={"show_type": "PERFORMANCE"},
    )

    confirmed = validate_success(
        api_client.confirm_entry(context["entries"][0]["id"], SS_HEADERS), 200
    )
    assert confirmed["entry_status"] == "CONFIRMED"
    assert confirmed["entry_fee_cents"] == 3910
    assert confirmed["levy_cents"] == 210
    assert confirmed["net_fee_cents"] == 3910
    assert confirmed["armband_number"] == 1
    assert confirmed["fee_basis"] == "PROVISIONAL"

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 3910
    assert show["levy_total_cents"] == 210
    assert show["fee_collected_cents"] == 3910


def test_three_conformation_dogs_take_eight_ring_minutes_not_nine():
    """The ceiling is taken once on the whole division, never per dog.

    PRD 3.6: "The base duration in minutes is the dog count multiplied by 60 and
    divided by that hourly rate, with the quotient rounded up to the next whole minute
    — and the rounding up is applied to the division alone, never to a per-dog figure,
    so three conformation dogs give 180 divided by 25 rounded up, which is 8 minutes,
    not three separate roundings totalling 9."

    Design: Corner/calculations/three_conformation_dogs_round_up_to_eight_ring_minutes_not_nine
    """
    context = setup_show_with_class(num_dogs=3, confirm_entries=True, close_class=True)

    block = plan_ring_block(
        context["show"], context["klass"], context["slot"],
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
    )
    assert block["scheduled_dog_count"] == 3
    assert block["conflict_free_minutes"] == 8
    assert block["judging_minutes_estimate"] == 8
    assert_instant_equals(block["block_end_at"], "2026-09-12T09:08:00Z", "block_end_at")
    assert block["block_status"] == "PLANNED"
    assert block["deferred_dog_count"] == 0


def test_one_tenth_of_a_degree_separates_green_from_amber():
    """The advisory comparison is inclusive at the bottom of each band.

    PRD 3.7: "The advisory then follows two thresholds: an index of 32.0 degrees or
    higher is `RED`, an index of 26.0 degrees or higher but below 32.0 is `AMBER`, and
    anything below 26.0 is `GREEN`."

    Design: Corner/calculations/heat_index_at_exactly_the_amber_floor_stops_being_green
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)

    green = validate_success(
        api_client.record_temperature_reading(
            show["id"], temperature_reading_payload(22.9, 65), SS_HEADERS
        ),
        200,
    )
    assert green["current_heat_index_c"] == pytest.approx(25.9, abs=0.01)
    assert green["current_advisory_level"] == "GREEN"
    assert green["temperature_reading_count"] == 1

    amber = validate_success(
        api_client.record_temperature_reading(
            show["id"], temperature_reading_payload(23.0, 65), SS_HEADERS
        ),
        200,
    )
    assert amber["current_heat_index_c"] == pytest.approx(26.0, abs=0.01)
    assert amber["current_advisory_level"] == "AMBER"
    assert amber["temperature_reading_count"] == 2
    assert amber["status"] == "APPROVED"


def test_an_obedience_score_of_exactly_one_hundred_and_seventy_earns_a_leg():
    """The qualifying comparison is inclusive, and a leg follows the qualification.

    PRD 3.8: "For the `OBEDIENCE` discipline, `total_faults` is simply the
    `obedience_deductions`, `final_score` is 200.0 less those deductions, and the run
    is `QUALIFIED` when the final score is 170.0 or higher and `NQ` otherwise."

    Design: Corner/calculations/obedience_score_at_exactly_the_qualifying_minimum_awards_a_leg
    """
    context = setup_class_ready_to_judge(
        num_dogs=1, class_level="PERFORMANCE", discipline="OBEDIENCE",
        show_overrides={"show_type": "PERFORMANCE"},
    )

    run = validate_success(
        api_client.create_performance_run(
            create_performance_run_payload(
                context["entries"][0]["id"], 150.0, 40.0, 38.0, obedience_deductions=30
            ),
            make_judge_headers(context["judge"]["id"]),
        ),
        201,
    )
    assert_performance_run(run)
    assert run["discipline"] == "OBEDIENCE"
    assert run["time_faults"] == pytest.approx(0.0, abs=0.01)
    assert run["total_faults"] == pytest.approx(30.0, abs=0.01)
    assert run["final_score"] == pytest.approx(170.0, abs=0.01)
    assert run["run_result"] == "QUALIFIED"
    assert run["title_leg_awarded"] is True

    dog = read_dog(context["dogs"][0])
    assert dog["qualifying_leg_counts"] == {"AGILITY": 0, "OBEDIENCE": 1, "RALLY": 0}
    assert dog["title_codes"] == []


def test_a_dog_wicketed_at_exactly_the_band_bound_belongs_in_the_lower_jump_class():
    """The height ladder closes at the top of each band.

    PRD 3.1: "The bounds are inclusive at the top of each band, so exactly 35.0 cm maps
    to the 30 cm height while 35.1 cm maps to 40 cm."

    Design: Corner/calculations/measured_height_at_exactly_the_table_bound_maps_to_the_lower_jump_class
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=0, class_level="PERFORMANCE", discipline="AGILITY",
        show_overrides={"show_type": "PERFORMANCE"},
        judge_overrides={"approved_performance_disciplines": ["AGILITY"]},
    )
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )
    measure_dog(dog, context["judge"], 35.0, "TEMP_CARD")

    entry = validate_success(
        api_client.create_entry(
            create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert entry["entry_status"] == "RECEIVED"
    assert entry["class_id"] == klass["id"]
    assert entry["dog_id"] == dog["id"]
    assert entry["armband_number"] is None
    assert entry["entry_fee_cents"] == 0
    assert entry["welfare_status"] == "CLEAR"
    assert entry["conflict_deferred"] is False

    measured = read_dog(dog)
    assert measured["measured_height_cm"] == pytest.approx(35.0, abs=0.01)
    assert measured["measurement_status"] == "TEMP_CARD"


def test_a_protest_filed_exactly_a_day_after_completion_is_still_in_time():
    """The window is anchored on the class and closes inclusively.

    PRD 3.9: "When the protested entry's class has reached `COMPLETED` or `ABANDONED`,
    the window runs for 24 hours from that class's `completed_at` and the comparison is
    inclusive, so a filing at exactly 24 hours after completion is accepted and one
    second later is not."

    Design: Corner/calculations/protest_filed_at_exactly_twenty_four_hours_after_completion_is_accepted
    """
    context = setup_completed_class(num_dogs=2)
    handler, entry = context["handler"], context["entries"][1]
    set_clock("2026-09-13T10:00:00Z")

    protest = validate_success(
        api_client.create_protest(
            create_protest_payload(
                context["show"]["id"], entry["id"], handler["id"],
                protest_type="JUDGING_CONDUCT",
                statement="Filed on the last second of the protest window.",
                deposit_cents=5000,
            ),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert protest["status"] == "FILED"
    assert protest["review_round"] == 0
    assert protest["deposit_refunded"] is False
    assert protest["deposit_cents"] == 5000
    assert protest["entry_id"] == entry["id"]
    assert protest["decided_at"] is None
    assert protest["resolution_code"] is None


def _five_dogs_in_one_class_and_two_of_them_in_a_second():
    """Two conformation classes on one panel slot: five dogs in B1, two of them in B2."""
    context = setup_show_with_class(num_dogs=5, num_entries=0)
    show, klass, slot, handler = (
        context["show"], context["klass"], context["slot"], context["handler"]
    )
    second_class = attach_judge(offer_class(show, class_code="B2"), slot)
    big = [
        confirm_entry(enter_dog(show, klass, dog, handler)) for dog in context["dogs"]
    ]
    small = [
        confirm_entry(enter_dog(show, second_class, context["dogs"][i], handler))
        for i in (0, 1)
    ]
    close_entries(klass)
    close_entries(second_class)
    set_clock("2026-09-12T09:00:00Z")
    open_day(show)
    big = [check_in(entry, "PRESENT") for entry in big]
    small = [check_in(entry, "PRESENT") for entry in small]

    context["second_class"] = second_class
    context["big_entries"] = big
    context["small_entries"] = small
    return context


def test_five_counted_dogs_pay_the_flat_second_tier_figure_and_make_a_major():
    """The points table is a step function on the counted-dog count, not a per-dog rate.

    PRD 3.8: "A count of 0 or 1 dog awards 0 points; 2 to 4 dogs awards 1 point; 5 to 9
    dogs awards 2 points; 10 to 17 dogs awards 3 points; 18 to 29 dogs awards 4 points;
    and 30 dogs or more awards 5 points."

    Design: Corner/calculations/five_counted_dogs_land_in_the_second_points_tier_and_make_a_major
    """
    context = _five_dogs_in_one_class_and_two_of_them_in_a_second()
    entries = context["big_entries"]

    judged = validate_success(
        api_client.complete_class(
            context["klass"]["id"],
            complete_class_payload([entry["id"] for entry in entries[:4]]),
            make_judge_headers(context["judge"]["id"]),
        ),
        200,
    )
    assert judged["status"] == "COMPLETED"
    assert judged["counted_dog_count"] == 5
    assert judged["base_points"] == 2
    assert judged["present_count"] == 5
    assert_instant_equals(
        judged["completed_at"], "2026-09-12T09:00:00Z", "completed_at"
    )

    winner = read_entry(entries[0])
    assert winner["entry_status"] == "JUDGED"
    assert winner["placement"] == 1
    assert winner["points_awarded"] == 2

    unplaced = read_entry(entries[4])
    assert unplaced["entry_status"] == "JUDGED"
    assert unplaced["placement"] is None
    assert unplaced["points_awarded"] == 0

    dog = read_dog(context["dogs"][0])
    assert dog["championship_points_total"] == 2
    assert dog["majors_count"] == 1
    assert dog["title_codes"] == []


def test_the_second_class_re_sums_the_dog_and_the_show_rather_than_incrementing_them():
    """Both rollups are re-derived from the entry rows, and a 1-point win is no major.

    PRD 3.8: "For every dog that gained points, `championship_points_total` is
    re-derived as the sum of `points_awarded` over all of that dog's entries and
    `majors_count` is re-derived as the number of that dog's entries whose
    `points_awarded` is 2 or more, two points being the threshold at which a win counts
    as a major."

    Design: Corner/calculations/show_points_total_re_aggregates_after_the_second_class_completes
    """
    context = _five_dogs_in_one_class_and_two_of_them_in_a_second()
    complete_class(
        context["klass"], context["judge"],
        [entry["id"] for entry in context["big_entries"][:4]],
    )

    judged = validate_success(
        api_client.complete_class(
            context["second_class"]["id"],
            complete_class_payload([entry["id"] for entry in context["small_entries"]]),
            make_judge_headers(context["judge"]["id"]),
        ),
        200,
    )
    assert judged["status"] == "COMPLETED"
    assert judged["counted_dog_count"] == 2
    assert judged["base_points"] == 1

    assert read_show(context["show"])["points_awarded_total"] == 3
    winner = read_dog(context["dogs"][0])
    assert winner["championship_points_total"] == 3
    assert winner["majors_count"] == 1

    runner_up = read_dog(context["dogs"][1])
    assert runner_up["championship_points_total"] == 0
    assert runner_up["majors_count"] == 0


def test_the_registry_writes_ch_at_exactly_three_points_including_one_major():
    """Titles are replayed from the dog rows when the filing is accepted.

    PRD 3.9: "The champion code `CH` is earned when the dog's
    `championship_points_total` is at least 3 *and* its `majors_count` is at least 1 —
    so exactly 3 points including exactly 1 major earns it."

    Design: Corner/calculations/registry_accept_records_ch_at_exactly_three_points_and_one_major
    """
    context = _five_dogs_in_one_class_and_two_of_them_in_a_second()
    complete_class(
        context["klass"], context["judge"],
        [entry["id"] for entry in context["big_entries"][:4]],
    )
    complete_class(
        context["second_class"], context["judge"],
        [entry["id"] for entry in context["small_entries"]],
    )
    close_show(context["show"])
    filing = raise_filing(context["show"])

    accepted = validate_success(
        api_client.adjudicate_registry_filing(
            filing["id"], adjudicate_filing_payload("ACCEPT"), RO_HEADERS
        ),
        200,
    )
    assert accepted["filing_status"] == "ACCEPTED"
    assert accepted["title_records_count"] == 1
    assert accepted["championship_points_total_filed"] == 3
    assert_instant_equals(
        accepted["adjudicated_at"], "2026-09-12T09:00:00Z", "adjudicated_at"
    )
    assert accepted["reject_reason"] is None
    assert accepted["amendment_count"] == 0

    assert read_dog(context["dogs"][0])["title_codes"] == ["CH"]
    assert read_dog(context["dogs"][1])["title_codes"] == []
    assert read_show(context["show"])["status"] == "RESULTS_FILED"


def test_three_refusals_eliminate_an_agility_run_that_still_scores_above_zero():
    """Elimination is decided before the fault arithmetic is consulted.

    PRD 3.8: "The outcome is decided in a fixed order: three or more refusals makes the
    `run_result` `ELIMINATED` regardless of the arithmetic, and this test is applied
    *before* the fault total is consulted, so a run with three refusals is eliminated
    even when its computed score is still above zero; otherwise a `total_faults` of
    exactly 0 is `QUALIFIED` and anything else is `NQ`."

    Design: Corner/calculations/third_refusal_eliminates_an_agility_run_whose_score_is_still_positive
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=0, class_level="PERFORMANCE", discipline="AGILITY",
        show_overrides={"show_type": "PERFORMANCE"},
        judge_overrides={"approved_performance_disciplines": ["AGILITY"]},
    )
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )
    measure_dog(dog, context["judge"], 35.0, "TEMP_CARD")
    entry = confirm_entry(enter_dog(show, klass, dog, handler))
    close_entries(klass)
    open_day(show)
    entry = check_in(entry, "PRESENT")

    run = validate_success(
        api_client.create_performance_run(
            create_performance_run_payload(
                entry["id"], 150.0, 40.0, 38.0, faults_count=0, refusals_count=3
            ),
            make_judge_headers(context["judge"]["id"]),
        ),
        201,
    )
    assert run["discipline"] == "AGILITY"
    assert run["time_faults"] == pytest.approx(0.0, abs=0.01)
    assert run["total_faults"] == pytest.approx(15.0, abs=0.01)
    assert run["final_score"] == pytest.approx(85.0, abs=0.01)
    assert run["run_result"] == "ELIMINATED"
    assert run["title_leg_awarded"] is False

    scored = read_dog(dog)
    assert scored["qualifying_leg_counts"]["AGILITY"] == 0
    assert scored["title_codes"] == []


def test_publishing_the_later_ring_defers_the_dogs_their_handler_shares():
    """The later block does the deferring, and only its own geometry widens.

    PRD 3.6: "When two such spans do intersect, the block with the later
    `block_start_at` is the deferring block, ties being broken in favour of the block
    with the later `created_at`."

    Design: Corner/calculations/publishing_an_overlapping_block_defers_the_shared_handler_dogs_in_the_later_ring
    """
    context = setup_show_with_class(num_dogs=2, confirm_entries=True)
    show, first_class, handler = (
        context["show"], context["klass"], context["handler"]
    )
    second_judge = register_judge(judge_number="J-78", full_name="Vera Lund")
    second_slot = confirmed_slot(show, second_judge)
    second_class = attach_judge(offer_class(show, class_code="B2"), second_slot)
    shared = [
        confirm_entry(enter_dog(show, second_class, dog, handler))
        for dog in context["dogs"]
    ]
    close_entries(first_class)
    close_entries(second_class)

    early = publish_ring_block(
        plan_ring_block(show, first_class, context["slot"], ring_number=1,
                        block_start_at="2026-09-12T09:00:00Z")
    )
    late = plan_ring_block(
        show, second_class, second_slot, ring_number=2,
        block_start_at="2026-09-12T09:02:00Z",
    )

    published = validate_success(
        api_client.publish_ring_block(late["id"], SS_HEADERS), 200
    )
    assert published["block_status"] == "PUBLISHED"
    assert_instant_equals(
        published["published_at"], "2026-08-10T09:00:00Z", "published_at"
    )
    assert published["scheduled_dog_count"] == 2
    assert published["conflict_free_minutes"] == 5
    assert published["deferred_dog_count"] == 2
    assert published["judging_minutes_estimate"] == 11
    assert_instant_equals(
        published["block_end_at"], "2026-09-12T09:13:00Z", "block_end_at"
    )

    assert read_entry(shared[0])["conflict_deferred"] is True
    assert read_entry(context["entries"][0])["conflict_deferred"] is False

    untouched = read_ring_block(early)
    assert untouched["deferred_dog_count"] == 0
    assert untouched["judging_minutes_estimate"] == 5
    assert_instant_equals(
        untouched["block_end_at"], "2026-09-12T09:05:00Z", "early block_end_at"
    )
    assert read_class(second_class)["status"] == "SCHEDULED"
