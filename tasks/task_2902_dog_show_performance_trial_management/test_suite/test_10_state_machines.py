"""Lifecycle transitions: what each declared move writes, what the undeclared ones
report, and which sibling rows a single transition reaches."""

import pytest

from test_helpers import ApiErrorId, api_client, validate_error, validate_success
from test_helpers.assertions import assert_instant_equals, assert_protest, assert_ring_block
from test_helpers.factories import (
    assign_judge_payload,
    complete_class_payload,
    create_protest_payload,
    create_ring_block_payload,
    respond_to_slot_payload,
    temperature_reading_payload,
)
from test_helpers.fixtures import (
    SO_HEADERS,
    SS_HEADERS,
    apply_for_show,
    approve_show,
    attach_judge,
    close_entries,
    confirm_entry,
    confirmed_slot,
    enter_dog,
    offer_class,
    open_day,
    plan_ring_block,
    publish_ring_block,
    read_class,
    read_club,
    read_dog,
    read_entry,
    read_judge,
    read_ring_block,
    read_show,
    read_show_version,
    read_slot,
    record_reading,
    register_club,
    return_application,
    set_clock,
    setup_class_ready_to_judge,
    setup_completed_class,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import make_club_officer_headers, make_handler_headers, make_judge_headers


def test_a_freshly_filed_protest_starts_at_round_zero():
    """Only opening the hearing moves `review_round`, so the create path leaves it at 0.

    PRD: "A newly filed protest has `status` `FILED`, `review_round` 0 and
    `deposit_refunded` false."

    Design: Corner/state_machines/protest_initial_state_is_filed_with_zero_review_round
    """
    context = setup_completed_class(num_dogs=2)
    entries, handler = context["entries"], context["handler"]

    protest = validate_success(
        api_client.create_protest(
            create_protest_payload(
                context["show"]["id"], entries[1]["id"], handler["id"],
                protest_type="JUDGING_CONDUCT",
                statement="Placement order does not match the ring order recorded by the steward.",
                deposit_cents=5000,
            ),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert_protest(protest)
    assert protest["status"] == "FILED"
    assert protest["review_round"] == 0
    assert protest["deposit_refunded"] is False
    assert protest["deposit_cents"] == 5000
    assert protest["evidence_request"] is None
    assert protest["evidence_note"] is None
    assert protest["reviewed_by_user_id"] is None
    assert protest["resolution_code"] is None
    assert protest["decided_at"] is None
    assert protest["show_id"] == context["show"]["id"]
    assert protest["entry_id"] == entries[1]["id"]
    assert protest["version"] == 1


def test_accepting_an_invitation_writes_the_slot_and_recounts_the_judge():
    """Acceptance is the transition that writes on both sides of the invitation.

    PRD: "Accepting moves the slot `PROPOSED → CONFIRMED`, stamps `responded_at` from
    the logical clock, recomputes the judge's `confirmed_slot_count`, and increases
    both the judge's `version` and the slot's `version` by one."

    Design: Corner/state_machines/panel_slot_accept_moves_proposed_to_confirmed
    """
    context = setup_show_with_class(num_dogs=0, slot_state="PROPOSED", assign_class=False)
    judge, slot = context["judge"], context["slot"]

    accepted = validate_success(
        api_client.respond_to_panel_slot(
            slot["id"], respond_to_slot_payload("ACCEPT"), make_judge_headers(judge["id"])
        ),
        200,
    )
    assert accepted["slot_status"] == "CONFIRMED"
    assert_instant_equals(accepted["responded_at"], "2026-08-10T09:00:00Z", "responded_at")
    assert accepted["decline_reason"] is None
    assert accepted["assigned_class_count"] == 0
    assert accepted["assigned_dog_capacity"] == 175

    refreshed_judge = read_judge(judge)
    assert refreshed_judge["confirmed_slot_count"] == 1
    assert refreshed_judge["version"] > judge["version"]


def test_a_show_cannot_be_closed_while_one_of_its_classes_has_never_been_judged():
    """The close gate is quantified over every class of the show.

    PRD: "Once judging is finished the secretary closes the show, moving it
    `IN_PROGRESS → COMPLETED`, which requires every class of the show to have reached
    `COMPLETED` or `ABANDONED`; a class still open reports
    `ERR_CLASSES_NOT_COMPLETE`."

    Design: Corner/state_machines/close_show_with_a_non_terminal_class_returns_classes_not_complete
    """
    context = setup_class_ready_to_judge(num_dogs=2, judging_clock=None)

    response = api_client.close_show(context["show"]["id"], SS_HEADERS)
    validate_error(response, ApiErrorId.ERR_CLASSES_NOT_COMPLETE, 409)

    show = read_show(context["show"])
    assert show["status"] == "IN_PROGRESS"
    assert show["points_awarded_total"] == 0
    assert read_class(context["klass"])["status"] == "CLOSED"


def test_approval_stamps_the_deciding_officer_and_consumes_one_of_the_clubs_events():
    """Approval writes the show, the officer identity and the club's counter at once.

    PRD: "Approval moves the show `SUBMITTED → APPROVED`, records the deciding
    officer's caller identifier in `approved_by_user_id`, stamps
    `approval_decided_at` from the logical clock, recomputes the club's
    `events_approved_count` so that this show now counts against it, and increases the
    show's `version` by one."

    Design: Corner/state_machines/approve_stamps_the_deciding_officer_and_increments_club_events_count
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    show = apply_for_show(club)
    submit_show(show, club)

    approved = validate_success(api_client.approve_show(show["id"], SO_HEADERS), 200)
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == "so-alpha"
    assert_instant_equals(
        approved["approval_decided_at"], "2026-08-10T09:00:00Z", "approval_decided_at"
    )
    assert_instant_equals(approved["submitted_at"], "2026-08-10T09:00:00Z", "submitted_at")
    assert approved["revision_count"] == 0

    refreshed_club = read_club(club)
    assert refreshed_club["events_approved_count"] == 1
    assert refreshed_club["annual_event_allowance"] == 2


def test_submitting_an_already_approved_show_reports_the_dedicated_state_identifier():
    """Submit is declared only from DRAFT and RETURNED, and the counter must not move.

    PRD: "submitting a show that is neither `DRAFT` nor `RETURNED` gives
    `ERR_SHOW_NOT_IN_DRAFT`"

    Design: Corner/state_machines/submit_on_an_approved_show_returns_show_not_in_draft
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)

    response = api_client.submit_show(show["id"], make_club_officer_headers(club["id"]))
    validate_error(response, ApiErrorId.ERR_SHOW_NOT_IN_DRAFT, 409)

    refreshed = read_show(show)
    assert refreshed["status"] == "APPROVED"
    assert refreshed["revision_count"] == 0
    assert refreshed["return_reason"] is None
    assert_instant_equals(refreshed["submitted_at"], "2026-08-10T09:00:00Z", "submitted_at")


def test_a_judge_who_has_declined_cannot_change_their_mind():
    """DECLINED is terminal, so the second answer is refused with the generic identifier.

    PRD: "Declining moves the slot `PROPOSED → DECLINED`, which is terminal, stamps
    `responded_at`, stores the supplied `decline_reason`, and increases the judge's
    `version` by one."

    Design: Corner/state_machines/second_response_on_a_declined_slot_returns_invalid_state
    """
    context = setup_show_with_class(
        num_dogs=0, slot_state="DECLINED", assign_class=False
    )
    judge, slot = context["judge"], context["slot"]

    response = api_client.respond_to_panel_slot(
        slot["id"], respond_to_slot_payload("ACCEPT"), make_judge_headers(judge["id"])
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE, 409)

    refreshed = read_slot(slot)
    assert refreshed["slot_status"] == "DECLINED"
    assert refreshed["decline_reason"] == "Travel conflict on that weekend"
    assert read_judge(judge)["confirmed_slot_count"] == 0


def test_replaying_close_entries_is_refused_before_the_ledger_is_touched_again():
    """The state gate protects the one reconciliation point of the fee ledger.

    PRD: "Closing a class whose `status` is not `OPEN` reports `ERR_CLASS_NOT_OPEN`."

    Design: Corner/state_machines/second_close_entries_on_a_closed_class_returns_class_not_open
    """
    context = setup_show_with_class(
        num_dogs=1, confirm_entries=True, close_class=True,
        class_overrides={"class_code": "B1"},
    )

    response = api_client.close_class_entries(context["klass"]["id"], SS_HEADERS)
    validate_error(response, ApiErrorId.ERR_CLASS_NOT_OPEN, 409)

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 4663
    assert show["levy_total_cents"] == 263
    assert show["fee_collected_cents"] == 4663
    assert show["fee_assessment_delta_cents"] == 0

    entry = read_entry(context["entries"][0])
    assert entry["fee_basis"] == "FINAL"
    assert entry["entry_fee_cents"] == 4663

    klass = read_class(context["klass"])
    assert klass["status"] == "CLOSED"
    assert klass["final_assessment_done"] is True


def test_a_returned_application_resubmits_without_rewinding_the_revision_count():
    """Rejoining SUBMITTED clears the reason text but never decreases the counter.

    PRD: "The club may then resubmit, moving `RETURNED → SUBMITTED`, which re-checks
    club standing and allowance exactly as the first submission did, re-stamps
    `submitted_at`, and clears `return_reason` back to null."

    Design: Corner/state_machines/returned_show_resubmits_clearing_the_reason_and_keeping_the_revision_count
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    show = apply_for_show(club)
    submit_show(show, club)
    return_application(show, "Entry window closes after the show date")

    resubmitted = validate_success(
        api_client.submit_show(show["id"], make_club_officer_headers(club["id"])), 200
    )
    assert resubmitted["status"] == "SUBMITTED"
    assert resubmitted["revision_count"] == 1
    assert resubmitted["return_reason"] is None
    assert_instant_equals(
        resubmitted["submitted_at"], "2026-08-10T09:00:00Z", "submitted_at"
    )
    assert resubmitted["approved_by_user_id"] is None


def test_a_decline_vacates_the_ring_block_drafted_against_the_unanswered_slot():
    """The decline cascade reaches down into a schedule the class never joined.

    PRD: "every ring block whose `slot_id` names this slot and whose `block_status`
    is `PLANNED` moves to `SUPERSEDED`, because the judge who was to officiate has
    withdrawn."

    Design: Corner/state_machines/declining_a_slot_supersedes_the_planned_ring_block_built_on_it
    """
    context = setup_show_with_class(num_dogs=0, slot_state="PROPOSED", assign_class=False)
    show, klass, judge, slot = (
        context["show"], context["klass"], context["judge"], context["slot"]
    )
    block = plan_ring_block(
        show, klass, slot, ring_number=1, block_start_at="2026-09-12T09:00:00Z"
    )

    declined = validate_success(
        api_client.respond_to_panel_slot(
            slot["id"],
            respond_to_slot_payload("DECLINE", decline_reason="Double-booked with a regional trial"),
            make_judge_headers(judge["id"]),
        ),
        200,
    )
    assert declined["slot_status"] == "DECLINED"
    assert declined["decline_reason"] == "Double-booked with a regional trial"

    vacated = read_ring_block(block)
    assert vacated["block_status"] == "SUPERSEDED"
    assert vacated["superseded_block_id"] is None
    assert vacated["scheduled_dog_count"] == 0
    assert vacated["judging_minutes_estimate"] == 0

    refreshed_class = read_class(klass)
    assert refreshed_class["status"] == "OPEN"
    assert refreshed_class["assigned_slot_id"] is None


def test_replacing_the_only_published_block_bubbles_the_class_back_to_closed():
    """The replacement is only PLANNED, so it cannot hold the class at SCHEDULED.

    PRD: "If the block that was superseded had been `PUBLISHED` and no published
    block remains for that class, the class reverts `SCHEDULED → CLOSED`; this
    revert leg may fire repeatedly, since a class can cycle
    `CLOSED → SCHEDULED → CLOSED` as its timetable is rebuilt."

    Design: Corner/state_machines/superseding_the_last_published_block_reverts_the_class_to_closed
    """
    context = setup_show_with_class(num_dogs=1, confirm_entries=True, close_class=True)
    show, klass, slot = context["show"], context["klass"], context["slot"]
    first = publish_ring_block(
        plan_ring_block(show, klass, slot, ring_number=1,
                        block_start_at="2026-09-12T09:00:00Z")
    )
    assert read_class(klass)["status"] == "SCHEDULED"

    replacement = validate_success(
        api_client.create_ring_block(
            create_ring_block_payload(
                show["id"], klass["id"], slot["id"], read_show_version(show),
                ring_number=2, block_start_at="2026-09-12T10:30:00Z",
            ),
            SS_HEADERS,
        ),
        201,
    )
    assert_ring_block(replacement)
    assert replacement["block_status"] == "PLANNED"
    assert replacement["superseded_block_id"] == first["id"]
    assert replacement["scheduled_dog_count"] == 1
    assert replacement["conflict_free_minutes"] == 3
    assert replacement["judging_minutes_estimate"] == 3
    assert_instant_equals(
        replacement["block_end_at"], "2026-09-12T10:33:00Z", "block_end_at"
    )
    assert replacement["published_at"] is None

    assert read_ring_block(first)["block_status"] == "SUPERSEDED"
    assert read_class(klass)["status"] == "CLOSED"


def test_attaching_a_class_publishes_the_slots_dog_ceiling():
    """Attachment writes the class and then adjusts the slot on the other side.

    PRD: "A successful attachment writes the class's `assigned_slot_id`, increases
    the slot's `assigned_class_count` by one, refreshes the slot's
    `assigned_dog_capacity`, and increases the class's `version` by one."

    Design: Corner/state_machines/assign_judge_increments_the_slot_class_count_and_publishes_its_dog_capacity
    """
    context = setup_show_with_class(num_dogs=0, assign_class=False)
    klass, slot = context["klass"], context["slot"]

    attached = validate_success(
        api_client.assign_judge_to_class(
            klass["id"], assign_judge_payload(slot["id"]), SS_HEADERS
        ),
        200,
    )
    assert attached["assigned_slot_id"] == slot["id"]
    assert attached["status"] == "OPEN"
    assert attached["version"] > klass["version"]

    refreshed_slot = read_slot(slot)
    assert refreshed_slot["assigned_class_count"] == 1
    assert refreshed_slot["assigned_dog_capacity"] == 175
    assert refreshed_slot["slot_status"] == "CONFIRMED"
    assert_instant_equals(
        refreshed_slot["responded_at"], "2026-08-10T09:00:00Z", "responded_at"
    )


def test_confirmation_reconciles_the_entry_the_show_ledger_and_the_class_counter():
    """One write lands on three rows, and the show absorbs the rounded entry amounts.

    PRD: "Confirmation mints the armband before it prices anything. Armbands are per
    dog, per show: if any entry of this same dog at this same show already carries an
    `armband_number`, the confirming entry inherits the lowest such number and the
    show's `armband_high_water` is left alone."

    Design: Corner/state_machines/entry_confirmation_syncs_the_show_ledger_and_the_class_counter
    """
    context = setup_show_with_class(num_dogs=1)
    entry = context["entries"][0]

    confirmed = validate_success(api_client.confirm_entry(entry["id"], SS_HEADERS), 200)
    assert confirmed["entry_status"] == "CONFIRMED"
    assert confirmed["armband_number"] == 1
    assert confirmed["entry_fee_cents"] == 4663
    assert confirmed["levy_cents"] == 263
    assert confirmed["net_fee_cents"] == 4663
    assert confirmed["fee_basis"] == "PROVISIONAL"
    assert confirmed["fee_refunded_cents"] == 0
    assert confirmed["welfare_status"] == "CLEAR"
    assert confirmed["conflict_deferred"] is False

    show = read_show(context["show"])
    assert show["fee_charged_cents"] == 4663
    assert show["levy_total_cents"] == 263
    assert show["fee_collected_cents"] == 4663
    assert show["fee_refunded_cents"] == 0
    assert show["fee_retained_cents"] == 0
    assert show["confirmed_entry_count"] == 1
    assert show["armband_high_water"] == 1

    klass = read_class(context["klass"])
    assert klass["entry_count"] == 1
    assert klass["present_count"] == 0


def _combined_outdoor_show_with_one_breed_and_one_performance_entry():
    """A COMBINED outdoor show, mid-day, one conformation entry and one performance entry."""
    context = setup_show_with_class(
        num_dogs=2, num_entries=1, confirm_entries=True,
        show_overrides={"show_type": "COMBINED", "outdoor_venue": True},
        class_level="BREED",
    )
    show, judge, handler = context["show"], context["judge"], context["handler"]
    performance_slot = confirmed_slot(show, judge, panel_role="PERFORMANCE_JUDGE")
    performance_class = attach_judge(
        offer_class(show, class_level="PERFORMANCE", discipline="OBEDIENCE"),
        performance_slot,
    )
    performance_entry = confirm_entry(
        enter_dog(show, performance_class, context["dogs"][1], handler)
    )
    close_entries(context["klass"])
    close_entries(performance_class)
    open_day(show)

    assert read_show(show)["current_advisory_level"] is None
    context["performance_class"] = performance_class
    context["breed_entry"] = context["entries"][0]
    context["performance_entry"] = performance_entry
    return context


def test_a_red_reading_holds_the_performance_entry_and_leaves_its_breed_sibling_clear():
    """The welfare cascade is conditional on the level, the venue and the class level.

    PRD: "When a reading raises the level to `RED` on a show whose `outdoor_venue` is
    true, every entry of that show that belongs to a `PERFORMANCE` class and whose
    `welfare_status` is `CLEAR` moves `CLEAR → HEAT_HOLD`, and each such entry's
    `version` increases by one."

    Design: Corner/state_machines/red_advisory_holds_only_the_performance_entries_of_an_outdoor_show
    """
    context = _combined_outdoor_show_with_one_breed_and_one_performance_entry()

    show = validate_success(
        api_client.record_temperature_reading(
            context["show"]["id"], temperature_reading_payload(29.0, 65), SS_HEADERS
        ),
        200,
    )
    assert show["current_heat_index_c"] == pytest.approx(32.0, abs=0.01)
    assert show["current_advisory_level"] == "RED"
    assert show["temperature_reading_count"] == 1

    held = read_entry(context["performance_entry"])
    assert held["welfare_status"] == "HEAT_HOLD"
    assert held["entry_status"] == "CONFIRMED"
    assert held["version"] > context["performance_entry"]["version"]

    assert read_entry(context["breed_entry"])["welfare_status"] == "CLEAR"


def test_the_next_reading_below_the_red_floor_lifts_the_hold_it_caused():
    """The hold is not a latch, and the clear leg runs even though AMBER is restricted.

    PRD: "When a later reading puts the level anywhere other than `RED`, every entry
    of the show still in `HEAT_HOLD` moves `HEAT_HOLD → CLEAR`."

    Design: Corner/state_machines/a_later_sub_red_reading_returns_the_held_performance_entry_to_clear
    """
    context = _combined_outdoor_show_with_one_breed_and_one_performance_entry()
    record_reading(context["show"], 29.0, 65)
    held = read_entry(context["performance_entry"])
    assert held["welfare_status"] == "HEAT_HOLD"

    show = validate_success(
        api_client.record_temperature_reading(
            context["show"]["id"], temperature_reading_payload(28.9, 65), SS_HEADERS
        ),
        200,
    )
    assert show["current_heat_index_c"] == pytest.approx(31.9, abs=0.01)
    assert show["current_advisory_level"] == "AMBER"
    assert show["temperature_reading_count"] == 2

    released = read_entry(context["performance_entry"])
    assert released["welfare_status"] == "CLEAR"
    assert released["entry_status"] == "CONFIRMED"
    assert released["armband_number"] == held["armband_number"]

    assert read_entry(context["breed_entry"])["welfare_status"] == "CLEAR"


def test_a_completed_class_cannot_be_judged_a_second_time():
    """The state gate outranks the placement-set check, so points are never doubled.

    PRD: "completing a class from any other status, gives `ERR_CLASS_NOT_READY`"

    Design: Corner/state_machines/completing_an_already_completed_class_returns_class_not_ready
    """
    context = setup_completed_class(num_dogs=2)
    klass, judge = context["klass"], context["judge"]
    placements = [entry["id"] for entry in context["entries"]]

    response = api_client.complete_class(
        klass["id"], complete_class_payload(placements), make_judge_headers(judge["id"])
    )
    validate_error(response, ApiErrorId.ERR_CLASS_NOT_READY, 409)

    refreshed = read_class(klass)
    assert refreshed["status"] == "COMPLETED"
    assert refreshed["counted_dog_count"] == 2
    assert refreshed["base_points"] == 1
    assert_instant_equals(
        refreshed["completed_at"], "2026-09-12T10:00:00Z", "completed_at"
    )

    assert read_show(context["show"])["points_awarded_total"] == 1
    winner = read_dog(context["dogs"][0])
    assert winner["championship_points_total"] == 1
    assert winner["majors_count"] == 0
