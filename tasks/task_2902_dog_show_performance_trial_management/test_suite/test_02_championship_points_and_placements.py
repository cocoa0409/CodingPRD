"""Championship points: the two counting scales, abandonment and vacated ribbons."""

from test_helpers import validate_paginated
from test_helpers.api_client import api_client
from test_helpers.fixtures import (
    SS_HEADERS,
    adjudicate_filing,
    attach_judge,
    begin_review,
    check_in,
    close_entries,
    close_show,
    complete_class,
    confirm_entry,
    confirmed_slot,
    decide_protest,
    enter_dog,
    file_protest,
    offer_class,
    open_day,
    raise_filing,
    read_class,
    read_dog,
    read_entry,
    read_filing,
    read_protest,
    read_show,
    register_dog,
    register_judge,
    setup_show_with_class,
    set_clock,
)


def _two_scales_side_by_side():
    """Two identical BREED classes, one on the show scale and one overridden."""
    context = setup_show_with_class(
        num_dogs=2, num_entries=0, class_overrides={"class_code": "GR-OPEN-D"}
    )
    show, slot, handler = context["show"], context["slot"], context["handler"]
    class_a = context["klass"]
    class_b = attach_judge(
        offer_class(
            show, class_code="GR-OPEN-B", points_scale_override="SCALE_B",
        ),
        slot,
    )
    dogs = context["dogs"] + [
        register_dog(handler, index=2), register_dog(handler, index=3)
    ]
    entries_a = [
        confirm_entry(enter_dog(show, class_a, dogs[i], handler)) for i in (0, 1)
    ]
    entries_b = [
        confirm_entry(enter_dog(show, class_b, dogs[i], handler)) for i in (2, 3)
    ]
    close_entries(class_a)
    close_entries(class_b)
    open_day(show)
    check_in(entries_a[0], "PRESENT")
    check_in(entries_a[1], "ABSENT")
    check_in(entries_b[0], "PRESENT")
    check_in(entries_b[1], "ABSENT")
    return {
        "show": show, "judge": context["judge"], "dogs": dogs,
        "class_a": class_a, "class_b": class_b,
        "entries_a": entries_a, "entries_b": entries_b,
    }


def test_scale_a_counts_the_absentee_and_awards_the_winner_a_point():
    """Under SCALE_A an absent dog still inflates the divisor.

    PRD 3.8: "Under `SCALE_A`, the traditional entered-dog count, the counted
    population is the class's entries whose `entry_status` is `CONFIRMED`,
    `CHECKED_IN`, `JUDGED` or `ABSENT` — absentees still inflate the divisor, so
    a class can award points on the strength of dogs that never entered the
    ring."

    Design: Difficulty/dual_variant_calc/championship_points_scale_a_versus_scale_b_on_dog_totals
    """
    context = _two_scales_side_by_side()
    complete_class(
        context["class_a"], context["judge"], [context["entries_a"][0]["id"]]
    )

    klass = read_class(context["class_a"])
    assert klass["counted_dog_count"] == 2
    assert klass["base_points"] == 1
    assert read_entry(context["entries_a"][0])["points_awarded"] == 1

    dog = read_dog(context["dogs"][0])
    assert dog["championship_points_total"] == 1
    assert dog["majors_count"] == 0


def test_scale_b_override_drops_the_absentee_and_awards_no_points():
    """The class-level override drops the absentee and the tier falls to zero.

    PRD 3.8: "Under `SCALE_B`, the present-dog count, the counted population is
    only those entries in `CHECKED_IN` or `JUDGED`; absentees and confirmed dogs
    that never checked in drop out, which can push the class down a tier or all
    the way to zero."

    Design: Difficulty/dual_variant_calc/championship_points_scale_a_versus_scale_b_on_dog_totals
    """
    context = _two_scales_side_by_side()
    complete_class(
        context["class_b"], context["judge"], [context["entries_b"][0]["id"]]
    )

    klass = read_class(context["class_b"])
    assert klass["counted_dog_count"] == 1
    assert klass["base_points"] == 0
    assert read_entry(context["entries_b"][0])["points_awarded"] == 0
    assert read_dog(context["dogs"][2])["championship_points_total"] == 0


def test_show_points_total_sums_the_award_of_both_scales():
    """The show total is re-summed over every entry, whatever scale priced it.

    PRD 3.8: "The show's `points_awarded_total` is re-summed over all its
    entries and is the conserved points quantity."

    Design: Difficulty/dual_variant_calc/championship_points_scale_a_versus_scale_b_on_dog_totals
    """
    context = _two_scales_side_by_side()
    complete_class(
        context["class_a"], context["judge"], [context["entries_a"][0]["id"]]
    )
    complete_class(
        context["class_b"], context["judge"], [context["entries_b"][0]["id"]]
    )

    assert read_show(context["show"])["points_awarded_total"] == 1


def _feeder_class_with_nobody_present():
    """A GROUP class fed by a BREED class whose two entries were both absent."""
    context = setup_show_with_class(
        num_dogs=2, num_entries=0, assign_class=False,
        class_overrides={"class_code": "GRP-SPORTING"}, class_level="GROUP",
        panel_role="GROUP_JUDGE",
    )
    show, handler, group_judge = context["show"], context["handler"], context["judge"]
    group_class = context["klass"]
    group_slot = context["slot"]
    attach_judge(group_class, group_slot)

    breed_judge = register_judge(judge_number="J-78", full_name="Vera Lund")
    breed_slot = confirmed_slot(show, breed_judge, panel_role="BREED_JUDGE")
    breed_class = attach_judge(
        offer_class(
            show, class_code="GR-OPEN-D", parent_class_id=group_class["id"],
        ),
        breed_slot,
    )
    entries = [
        confirm_entry(enter_dog(show, breed_class, dog, handler))
        for dog in context["dogs"]
    ]
    close_entries(breed_class)
    close_entries(group_class)
    open_day(show)
    entries = [check_in(entry, "ABSENT") for entry in entries]
    return {
        "show": show, "dogs": context["dogs"], "entries": entries,
        "breed_class": breed_class, "group_class": group_class,
        "breed_judge": breed_judge, "group_judge": group_judge,
    }


def test_empty_placement_set_abandons_the_class_and_awards_nothing():
    """A class where nobody turned up is abandoned rather than completed.

    PRD 3.8: "The abandonment stamps `completed_at` from the logical clock
    exactly as a completion does, sets `counted_dog_count` to 0 and
    `base_points` to 0, changes no entry's `entry_status`, awards no points,
    creates no promotion entry"

    Design: Difficulty/boundary_precision_check/empty_present_set_abandons_class_without_points
    """
    context = _feeder_class_with_nobody_present()
    set_clock("2026-09-12T10:00:00Z")

    complete_class(context["breed_class"], context["breed_judge"], [])

    klass = read_class(context["breed_class"])
    assert klass["status"] == "ABANDONED"
    assert klass["present_count"] == 0
    assert klass["counted_dog_count"] == 0
    assert klass["base_points"] == 0
    assert klass["entry_count"] == 2


def test_abandonment_leaves_the_absent_entries_and_their_dogs_untouched():
    """Absent entries keep their status and gain no points from abandonment.

    PRD 3.8: "An abandoned class contributes a `base_points` of 0 to any parent
    class that later looks for its feeders' best figure."

    Design: Difficulty/boundary_precision_check/empty_present_set_abandons_class_without_points
    """
    context = _feeder_class_with_nobody_present()
    set_clock("2026-09-12T10:00:00Z")

    complete_class(context["breed_class"], context["breed_judge"], [])

    first = read_entry(context["entries"][0])
    assert first["entry_status"] == "ABSENT"
    assert first["points_awarded"] == 0
    assert first["placement"] is None
    assert read_dog(context["dogs"][0])["championship_points_total"] == 0
    assert read_show(context["show"])["points_awarded_total"] == 0


def test_abandonment_promotes_nobody_into_the_parent_group_class():
    """No promotion entry is created, so the group ring stays empty.

    PRD 3.8: "If the class names a `parent_class_id`, a promotion entry is
    created in that parent class for the winning dog"

    Design: Difficulty/boundary_precision_check/empty_present_set_abandons_class_without_points
    """
    context = _feeder_class_with_nobody_present()
    set_clock("2026-09-12T10:00:00Z")

    complete_class(context["breed_class"], context["breed_judge"], [])

    rows, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, {"class_id": context["group_class"]["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_class(context["group_class"])["status"] == "CLOSED"


def _five_dog_class_with_accepted_filing_and_protest():
    """Five judged entries, an accepted filing, and a protest under review."""
    context = setup_show_with_class(
        num_dogs=5, confirm_entries=True, close_class=True, open_show=True,
        class_overrides={"class_code": "GR-OPEN-D"},
    )
    entries = [check_in(entry, "PRESENT") for entry in context["entries"]]
    set_clock("2026-09-12T10:00:00Z")
    complete_class(
        context["klass"], context["judge"], [entry["id"] for entry in entries[:4]]
    )
    close_show(context["show"])
    filing = adjudicate_filing(raise_filing(context["show"]), "ACCEPT")
    protest = file_protest(
        context["show"], entries[0], context["handler"],
        protest_type="JUDGING_CONDUCT",
        statement="Winner was moved up after the ribbons were handed out",
        deposit_cents=5000,
    )
    context["entries"] = entries
    context["filing"] = filing
    context["protest"] = begin_review(protest, "so-beta")
    return context


def test_vacated_placement_clears_the_winner_and_moves_every_ribbon_up():
    """The vacated entry stays judged while the rest of the order closes up.

    PRD 3.9: "A `VACATE_PLACEMENT` remedy leaves the entry's `entry_status`
    alone. In both cases the first link clears the entry's `placement` to null
    and sets its `points_awarded` to 0."

    Design: Difficulty/compensating_invariant/points_conservation_after_vacated_placement
    """
    context = _five_dog_class_with_accepted_filing_and_protest()

    decide_protest(context["protest"], "UPHOLD", "VACATE_PLACEMENT", "so-beta")

    protest = read_protest(context["protest"])
    assert protest["status"] == "UPHELD"
    assert protest["resolution_code"] == "VACATE_PLACEMENT"
    assert protest["deposit_refunded"] is True

    rows = [read_entry(entry) for entry in context["entries"]]
    assert rows[0]["entry_status"] == "JUDGED"
    assert rows[0]["placement"] is None
    assert rows[0]["points_awarded"] == 0
    assert [row["placement"] for row in rows[1:]] == [1, 2, 3, None]


def test_vacating_a_placement_conserves_the_points_it_moves_to_another_dog():
    """The divisor is unchanged, so the same two points land on the new winner.

    PRD 3.9: "the championship points award re-runs over the class from scratch,
    rewriting `counted_dog_count`, `base_points` and each remaining entry's
    `points_awarded`."

    Design: Difficulty/compensating_invariant/points_conservation_after_vacated_placement
    """
    context = _five_dog_class_with_accepted_filing_and_protest()

    decide_protest(context["protest"], "UPHOLD", "VACATE_PLACEMENT", "so-beta")

    klass = read_class(context["klass"])
    assert klass["counted_dog_count"] == 5
    assert klass["base_points"] == 2
    assert read_entry(context["entries"][1])["points_awarded"] == 2

    dog_one, dog_two, dog_three = (read_dog(dog) for dog in context["dogs"][:3])
    assert (dog_one["championship_points_total"], dog_one["majors_count"]) == (0, 0)
    assert (dog_two["championship_points_total"], dog_two["majors_count"]) == (2, 1)
    assert dog_three["championship_points_total"] == 0
    assert read_show(context["show"])["points_awarded_total"] == 2


def test_vacated_placement_reopens_the_accepted_filing_for_amendment():
    """The upheld remedy pushes the accepted filing back to pending.

    PRD 3.9: "that filing moves `ACCEPTED → PENDING`, its `amendment_count`
    increases by one, its `championship_points_total_filed` is recomputed from
    the amended `points_awarded_total`"

    Design: Difficulty/compensating_invariant/points_conservation_after_vacated_placement
    """
    context = _five_dog_class_with_accepted_filing_and_protest()

    decide_protest(context["protest"], "UPHOLD", "VACATE_PLACEMENT", "so-beta")

    filing = read_filing(context["filing"])
    assert filing["filing_status"] == "PENDING"
    assert filing["amendment_count"] == 1
    assert filing["championship_points_total_filed"] == 2
    assert filing["title_records_count"] == 0
    assert read_show(context["show"])["status"] == "COMPLETED"
