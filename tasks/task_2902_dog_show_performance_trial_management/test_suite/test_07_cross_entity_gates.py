"""Two gates that read the state of a different row: a ring block that waits on its
judge, and a registry filing that waits on a sibling protest."""

from test_helpers import ApiErrorId, api_client, validate_error, validate_paginated, validate_success
from test_helpers.assertions import assert_instant_equals
from test_helpers.factories import create_registry_filing_payload
from test_helpers.fixtures import (
    SS_HEADERS,
    begin_review,
    check_in,
    close_show,
    complete_class,
    decide_protest,
    file_protest,
    plan_ring_block,
    read_class,
    read_protest,
    read_ring_block,
    read_show,
    read_slot,
    respond_to_slot,
    setup_show_with_class,
)


def _planned_block_against_an_unanswered_invitation():
    """A block legitimately planned while its judge has still not accepted."""
    context = setup_show_with_class(
        num_dogs=2,
        confirm_entries=True,
        close_class=True,
        slot_state="PROPOSED",
        class_overrides={"class_code": "GR-OPEN-D"},
    )
    context["block"] = plan_ring_block(
        context["show"], context["klass"], context["slot"],
        ring_number=1, block_start_at="2026-09-12T09:00:00Z",
    )
    return context


def test_publishing_a_block_whose_judge_has_not_accepted_is_refused():
    """The gate reads the slot at publication time, not at planning time.

    PRD: "It requires the block to be `PLANNED`, its slot to be `CONFIRMED`
    (otherwise `ERR_SLOT_NOT_CONFIRMED`), and its class to be `CLOSED`."

    Design: Difficulty/cross_entity_state_dependency/ring_block_publish_requires_confirmed_panel_slot
    """
    context = _planned_block_against_an_unanswered_invitation()

    response = api_client.publish_ring_block(context["block"]["id"], SS_HEADERS)
    validate_error(response, ApiErrorId.ERR_SLOT_NOT_CONFIRMED, 409)

    block = read_ring_block(context["block"])
    assert block["block_status"] == "PLANNED"
    assert block["published_at"] is None
    assert read_class(context["klass"])["status"] == "CLOSED"


def test_the_judge_accepting_is_the_only_change_the_same_publish_needs():
    """Nothing about the block moves between the refused and the accepted publish.

    PRD: "On success, `published_at` is stamped from the logical clock, the class
    moves `CLOSED → SCHEDULED`, handler ring-conflict resolution runs, and the
    block's `version` increases by one."

    Design: Difficulty/cross_entity_state_dependency/ring_block_publish_requires_confirmed_panel_slot
    """
    context = _planned_block_against_an_unanswered_invitation()
    api_client.publish_ring_block(context["block"]["id"], SS_HEADERS)

    respond_to_slot(context["slot"], context["judge"], "ACCEPT")
    assert read_slot(context["slot"])["slot_status"] == "CONFIRMED"

    published = validate_success(
        api_client.publish_ring_block(context["block"]["id"], SS_HEADERS), 200
    )
    assert published["block_status"] == "PUBLISHED"
    assert_instant_equals(published["published_at"], "2026-08-10T09:00:00Z", "published_at")
    assert published["judging_minutes_estimate"] == 5
    assert_instant_equals(
        published["block_end_at"], "2026-09-12T09:05:00Z", "block_end_at"
    )
    assert read_class(context["klass"])["status"] == "SCHEDULED"


def _closed_show_with_an_open_protest():
    """A completed class on a closed show, with one protest still under review."""
    context = setup_show_with_class(
        num_dogs=3,
        confirm_entries=True,
        close_class=True,
        open_show=True,
        class_overrides={"class_code": "GR-OPEN-D"},
    )
    entries = context["entries"]
    check_in(entries[0])
    check_in(entries[1])
    complete_class(
        context["klass"], context["judge"], [entries[0]["id"], entries[1]["id"]]
    )
    context["show"] = close_show(context["show"])

    protest = file_protest(
        context["show"], entries[1], context["handler"],
        protest_type="JUDGING_CONDUCT",
        statement="Placement order was announced incorrectly",
        deposit_cents=5000,
    )
    context["protest"] = begin_review(protest)
    return context


def test_a_filing_may_not_be_raised_while_a_protest_of_the_show_is_still_open():
    """The blocking condition is a sibling row that has not reached a terminal state.

    PRD: "when no protest of the show is still `FILED`, `UNDER_REVIEW` or
    `EVIDENCE_REQUESTED` (otherwise `ERR_OPEN_PROTEST_BLOCKS_FILING`)"

    Design: Difficulty/cross_entity_state_dependency/registry_filing_creation_blocked_by_open_protest
    """
    context = _closed_show_with_an_open_protest()

    response = api_client.create_registry_filing(
        create_registry_filing_payload(context["show"]["id"]), SS_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_OPEN_PROTEST_BLOCKS_FILING, 409)

    rows, meta = validate_paginated(
        api_client.list_show_registry_filings(context["show"]["id"], SS_HEADERS)
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_dismissing_the_protest_is_enough_to_let_the_same_filing_through():
    """A dismissal forfeits the deposit and changes no result, but does unblock filing.

    PRD: "The deposit turns on the outcome and nothing else: `deposit_refunded`
    becomes true exactly when the protest is upheld, and stays false on a dismissal,
    where the deposit is forfeited."

    Design: Difficulty/cross_entity_state_dependency/registry_filing_creation_blocked_by_open_protest
    """
    context = _closed_show_with_an_open_protest()
    api_client.create_registry_filing(
        create_registry_filing_payload(context["show"]["id"]), SS_HEADERS
    )

    decide_protest(context["protest"], "DISMISS", "NO_ACTION")
    protest = read_protest(context["protest"])
    assert protest["status"] == "DISMISSED"
    assert protest["deposit_refunded"] is False

    filing = validate_success(
        api_client.create_registry_filing(
            create_registry_filing_payload(context["show"]["id"]), SS_HEADERS
        ),
        201,
    )
    assert filing["filing_status"] == "PENDING"
    assert filing["championship_points_total_filed"] == 1
    assert filing["title_records_count"] == 0
    assert filing["amendment_count"] == 0
    assert_instant_equals(filing["filed_at"], "2026-08-10T09:00:00Z", "filed_at")
    assert read_show(context["show"])["status"] == "COMPLETED"
