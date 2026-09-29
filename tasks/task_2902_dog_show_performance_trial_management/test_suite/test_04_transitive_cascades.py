"""Two four-link cascades: a withdrawal through the schedule and an upheld protest
through already-filed results."""

from test_helpers.assertions import assert_instant_equals
from test_helpers.fixtures import (
    adjudicate_filing,
    begin_review,
    check_in,
    close_entries,
    close_show,
    complete_class,
    confirm_entry,
    decide_protest,
    declare_season,
    enter_dog,
    file_protest,
    open_day,
    plan_ring_block,
    publish_ring_block,
    raise_filing,
    read_class,
    read_dog,
    read_entry,
    read_filing,
    read_protest,
    read_ring_block,
    read_show,
    read_show_version,
    register_dog,
    setup_scheduling_ready_show,
    set_clock,
)


def _seasonable_two_class_show():
    """The same two-ring show, but with a bitch leading the first class."""
    context = setup_scheduling_ready_show(
        num_classes=2, judges=2, dogs_per_class=[0, 0]
    )
    show, handler = context["show"], context["handler"]
    dogs = [
        register_dog(handler, index=0, sex="BITCH"),
        register_dog(handler, index=1),
        register_dog(handler, index=2),
        register_dog(handler, index=3),
        register_dog(handler, index=4),
    ]
    first = [
        confirm_entry(enter_dog(show, context["classes"][0], dogs[i], handler))
        for i in range(3)
    ]
    second = [
        confirm_entry(enter_dog(show, context["classes"][1], dogs[i], handler))
        for i in (3, 4)
    ]
    close_entries(context["classes"][0])
    close_entries(context["classes"][1])

    block_one = plan_ring_block(
        show, context["classes"][0], context["slots"][0],
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
        expected_show_version=read_show_version(show),
    )
    block_two = plan_ring_block(
        show, context["classes"][1], context["slots"][1],
        ring_number=2, block_start_at="2026-09-12T09:05:00Z",
        expected_show_version=read_show_version(show),
    )
    publish_ring_block(block_one)
    publish_ring_block(block_two)

    context["dogs"] = dogs
    context["entries_by_class"] = [first, second]
    context["block_one"], context["block_two"] = block_one, block_two
    return context


def test_withdrawal_settles_the_money_and_drops_the_class_population():
    """The first two links: the entry withdraws and its class shrinks.

    PRD 3.7: "Because the entry left the confirmed population, the class's
    `entry_count` — and its `present_count` when the entry had already checked in
    — and the assigned slot's `assigned_dog_capacity` are refreshed."

    Design: Difficulty/transitive_cascade/season_declaration_cascade_through_class_slot_and_ring_schedule
    """
    context = _seasonable_two_class_show()
    first_class_entries = context["entries_by_class"][0]

    withdrawn = declare_season(first_class_entries[0], context["handler"])
    assert withdrawn["entry_status"] == "WITHDRAWN"
    assert withdrawn["welfare_status"] == "SEASON_DECLARED"
    assert withdrawn["fee_refunded_cents"] == 3987
    assert withdrawn["net_fee_cents"] == 210

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 17745
    assert show["fee_refunded_cents"] == 3987
    assert show["fee_retained_cents"] == 210
    assert show["fee_collected_cents"] == 13758
    assert read_class(context["classes"][0])["entry_count"] == 2


def test_withdrawal_shrinks_the_ring_block_of_the_class_it_touched():
    """The third link re-derives the block geometry of the withdrawn dog's class.

    PRD 3.7: "Because the class's dog count changed, every `PLANNED` or
    `PUBLISHED` block of that class re-derives its `scheduled_dog_count`,
    `judging_minutes_estimate` and `block_end_at`."

    Design: Difficulty/transitive_cascade/season_declaration_cascade_through_class_slot_and_ring_schedule
    """
    context = _seasonable_two_class_show()

    declare_season(context["entries_by_class"][0][0], context["handler"])

    block = read_ring_block(context["block_one"])
    assert block["scheduled_dog_count"] == 2
    assert block["conflict_free_minutes"] == 5
    assert block["judging_minutes_estimate"] == 5
    assert_instant_equals(
        block["block_end_at"], "2026-09-12T09:05:00Z", "block_one.block_end_at"
    )


def test_withdrawal_un_defers_the_entries_of_the_other_class_entirely():
    """The fourth link lands on a class the trigger never touched.

    PRD 3.6: "When no pair intersects, every `conflict_deferred` is false, every
    `deferred_dog_count` collapses to 0, and every `block_end_at` shrinks back to
    its unbuffered value."

    Design: Difficulty/transitive_cascade/season_declaration_cascade_through_class_slot_and_ring_schedule
    """
    context = _seasonable_two_class_show()

    declare_season(context["entries_by_class"][0][0], context["handler"])

    block = read_ring_block(context["block_two"])
    assert block["deferred_dog_count"] == 0
    assert block["judging_minutes_estimate"] == 5
    assert_instant_equals(
        block["block_end_at"], "2026-09-12T09:10:00Z", "block_two.block_end_at"
    )
    for entry in context["entries_by_class"][1]:
        assert read_entry(entry)["conflict_deferred"] is False
    for entry in context["entries_by_class"][0][1:]:
        assert read_entry(entry)["entry_fee_cents"] == 3387


def _filed_results_with_a_protest_against_the_winner():
    """Five judged entries, an accepted filing, and a protest under review."""
    context = setup_scheduling_ready_show(num_classes=1, judges=1, dogs_per_class=[5])
    entries = context["entries_by_class"][0]
    close_entries(context["klass"])
    open_day(context["show"])
    entries = [check_in(entry, "PRESENT") for entry in entries]
    set_clock("2026-09-12T10:00:00Z")
    complete_class(
        context["klass"], context["judge"], [entry["id"] for entry in entries[:4]]
    )
    close_show(context["show"])
    filing = adjudicate_filing(raise_filing(context["show"]), "ACCEPT")
    protest = file_protest(
        context["show"], entries[0], context["handler"],
        protest_type="ELIGIBILITY",
        statement="Winning dog was shown in the wrong class",
        deposit_cents=5000,
    )
    context["entries"] = entries
    context["filing"] = filing
    context["protest"] = begin_review(protest, "so-beta")
    return context


def test_upholding_a_protest_disqualifies_the_entry_and_vacates_its_ribbon():
    """The first link disqualifies the winner and clears its award.

    PRD 3.9: "A `DISQUALIFY_ENTRY` remedy moves the protested entry
    `CHECKED_IN → DISQUALIFIED` or `JUDGED → DISQUALIFIED`."

    Design: Difficulty/transitive_cascade/upheld_protest_cascade_through_placements_points_titles_and_filing
    """
    context = _filed_results_with_a_protest_against_the_winner()

    decide_protest(context["protest"], "UPHOLD", "DISQUALIFY_ENTRY", "so-beta")

    protest = read_protest(context["protest"])
    assert protest["status"] == "UPHELD"
    assert protest["resolution_code"] == "DISQUALIFY_ENTRY"
    assert protest["deposit_refunded"] is True

    first = read_entry(context["entries"][0])
    assert first["entry_status"] == "DISQUALIFIED"
    assert first["placement"] is None
    assert first["points_awarded"] == 0


def test_disqualification_shrinks_the_divisor_and_reprices_the_new_winner():
    """The second link re-runs the award over a class that just lost a dog.

    PRD 3.8: "Under both scales `WITHDRAWN` and `DISQUALIFIED` entries are
    excluded, and that exclusion is the only status treatment the two scales
    agree on."

    Design: Difficulty/transitive_cascade/upheld_protest_cascade_through_placements_points_titles_and_filing
    """
    context = _filed_results_with_a_protest_against_the_winner()

    decide_protest(context["protest"], "UPHOLD", "DISQUALIFY_ENTRY", "so-beta")

    rows = [read_entry(entry) for entry in context["entries"]]
    assert [row["placement"] for row in rows[1:]] == [1, 2, 3, None]
    assert rows[1]["points_awarded"] == 1
    assert rows[2]["points_awarded"] == 0

    klass = read_class(context["klass"])
    assert klass["counted_dog_count"] == 4
    assert klass["base_points"] == 1
    assert klass["status"] == "COMPLETED"


def test_disqualification_rewrites_the_dog_rollups_and_the_show_total():
    """The third link re-derives every affected dog and re-sums the show.

    PRD 3.9: "The third link re-derives, for every affected dog,
    `championship_points_total` and `majors_count` from that dog's entries, and
    re-sums the show's `points_awarded_total` — a disqualification never simply
    subtracts."

    Design: Difficulty/transitive_cascade/upheld_protest_cascade_through_placements_points_titles_and_filing
    """
    context = _filed_results_with_a_protest_against_the_winner()

    decide_protest(context["protest"], "UPHOLD", "DISQUALIFY_ENTRY", "so-beta")

    first_dog = read_dog(context["dogs"][0])
    assert first_dog["championship_points_total"] == 0
    assert first_dog["majors_count"] == 0
    assert first_dog["title_codes"] == []
    assert read_dog(context["dogs"][1])["championship_points_total"] == 1
    assert read_show(context["show"])["points_awarded_total"] == 1


def test_disqualification_reopens_the_filing_and_pulls_the_show_back():
    """The fourth link reaches the registry and un-files the results.

    PRD 3.9: "The show itself moves `RESULTS_FILED → COMPLETED`, and the
    filing's `version` increases by one."

    Design: Difficulty/transitive_cascade/upheld_protest_cascade_through_placements_points_titles_and_filing
    """
    context = _filed_results_with_a_protest_against_the_winner()

    decide_protest(context["protest"], "UPHOLD", "DISQUALIFY_ENTRY", "so-beta")

    filing = read_filing(context["filing"])
    assert filing["filing_status"] == "PENDING"
    assert filing["amendment_count"] == 1
    assert filing["championship_points_total_filed"] == 1
    assert read_show(context["show"])["status"] == "COMPLETED"
