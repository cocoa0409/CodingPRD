"""The protest evidence loop and the two independent axes of an entry."""

from test_helpers.fixtures import (
    begin_review,
    check_in,
    file_protest,
    read_class,
    read_entry,
    read_protest,
    read_show,
    record_reading,
    request_evidence,
    resubmit_evidence,
    setup_show_with_class,
)


def _filed_protest_on_a_checked_in_entry():
    """A protest sitting in FILED against the checked-in entry of a closed class."""
    context = setup_show_with_class(
        num_dogs=2, confirm_entries=True, close_class=True, open_show=True,
        class_overrides={"class_code": "GR-OPEN-D"},
    )
    entries = context["entries"]
    context["entries"] = [
        check_in(entries[0], "PRESENT"), check_in(entries[1], "ABSENT")
    ]
    context["protest"] = file_protest(
        context["show"], context["entries"][0], context["handler"],
        protest_type="JUDGING_CONDUCT",
        statement="Ring steward misread the armband order",
        deposit_cents=5000,
    )
    return context


def test_a_newly_filed_protest_starts_at_review_round_zero():
    """Filing records no review round at all until a hearing opens.

    PRD 3.9: "A newly filed protest has `status` `FILED`, `review_round` 0 and
    `deposit_refunded` false."

    Design: Difficulty/non_linear_state_machine/protest_evidence_cycle_second_review_round
    """
    context = _filed_protest_on_a_checked_in_entry()

    protest = read_protest(context["protest"])
    assert protest["status"] == "FILED"
    assert protest["review_round"] == 0
    assert protest["deposit_refunded"] is False


def test_review_round_counts_every_entry_into_review_not_distinct_protests():
    """Two full evidence adjournments leave the counter reading three.

    PRD 3.9: "This loop may run any number of rounds, and `review_round`
    therefore counts entries into review rather than distinct protests."

    Design: Difficulty/non_linear_state_machine/protest_evidence_cycle_second_review_round
    """
    context = _filed_protest_on_a_checked_in_entry()
    protest, handler = context["protest"], context["handler"]

    begin_review(protest, "so-beta")
    request_evidence(protest, "Provide the ring steward's marked catalog page", "so-beta")
    resubmit_evidence(protest, handler, "Catalog page attached")
    request_evidence(protest, "Also provide the armband photograph", "so-beta")
    resubmit_evidence(protest, handler, "Photograph attached")

    row = read_protest(protest)
    assert row["status"] == "UNDER_REVIEW"
    assert row["review_round"] == 3


def test_the_second_evidence_cycle_overwrites_the_stored_evidence_texts():
    """The latest request and answer are the ones the protest carries.

    PRD 3.9: "The filing handler — and only the filing handler — then answers,
    moving the protest `EVIDENCE_REQUESTED → UNDER_REVIEW`, storing the supplied
    `evidence_note` and increasing `review_round` by one again."

    Design: Difficulty/non_linear_state_machine/protest_evidence_cycle_second_review_round
    """
    context = _filed_protest_on_a_checked_in_entry()
    protest, handler = context["protest"], context["handler"]

    begin_review(protest, "so-beta")
    request_evidence(protest, "Provide the ring steward's marked catalog page", "so-beta")
    resubmit_evidence(protest, handler, "Catalog page attached")
    request_evidence(protest, "Also provide the armband photograph", "so-beta")
    resubmit_evidence(protest, handler, "Photograph attached")

    row = read_protest(protest)
    assert row["evidence_request"] == "Also provide the armband photograph"
    assert row["evidence_note"] == "Photograph attached"
    assert row["deposit_refunded"] is False
    assert row["decided_at"] is None
    assert read_entry(context["entries"][0])["entry_status"] == "CHECKED_IN"


def _outdoor_performance_show_on_a_red_advisory():
    """An outdoor combined show whose performance entries are held on heat."""
    context = setup_show_with_class(
        num_dogs=2, confirm_entries=True, close_class=True, open_show=True,
        class_level="PERFORMANCE", discipline="OBEDIENCE",
        class_overrides={"class_code": "OB-NOVICE-A"},
        show_overrides={"show_type": "COMBINED", "outdoor_venue": True},
    )
    record_reading(context["show"], 29.0, 65)
    return context


def test_a_red_reading_moves_the_welfare_axis_without_touching_the_entry_status():
    """The heat hold lands on the welfare axis alone.

    PRD 3.7: "Neither move touches `entry_status`: the two axes are independent,
    and an entry on a heat hold is still a confirmed entry."

    Design: Difficulty/non_linear_state_machine/entry_parallel_welfare_and_competition_axes
    """
    context = _outdoor_performance_show_on_a_red_advisory()

    show = read_show(context["show"])
    assert show["current_heat_index_c"] == 32.0
    assert show["current_advisory_level"] == "RED"
    assert show["temperature_reading_count"] == 1

    for entry in context["entries"]:
        row = read_entry(entry)
        assert row["entry_status"] == "CONFIRMED"
        assert row["welfare_status"] == "HEAT_HOLD"


def test_a_held_entry_still_checks_in_and_keeps_its_heat_hold():
    """Check-in advances the competition axis and leaves the hold in place.

    PRD 3.7: "a `HEAT_HOLD` entry checks in perfectly normally, which is the
    whole point of keeping the axes separate."

    Design: Difficulty/non_linear_state_machine/entry_parallel_welfare_and_competition_axes
    """
    context = _outdoor_performance_show_on_a_red_advisory()

    checked_in = check_in(context["entries"][0], "PRESENT")
    assert checked_in["entry_status"] == "CHECKED_IN"
    assert checked_in["welfare_status"] == "HEAT_HOLD"

    untouched = read_entry(context["entries"][1])
    assert untouched["entry_status"] == "CONFIRMED"
    assert untouched["welfare_status"] == "HEAT_HOLD"
    assert read_class(context["klass"])["present_count"] == 1
