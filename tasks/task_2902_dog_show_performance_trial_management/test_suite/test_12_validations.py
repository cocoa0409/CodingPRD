"""The validation ladder seen one rung at a time: which rule fires, and what the
refused request leaves behind."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_instant_equals, assert_three_fractional_digits
from test_helpers.factories import (
    assign_judge_payload,
    complete_class_payload,
    create_entry_payload,
    create_protest_payload,
    measurement_payload,
)
from test_helpers.fixtures import (
    SS_HEADERS,
    attach_judge,
    confirm_entry,
    declare_season,
    measure_dog,
    offer_class,
    read_class,
    read_dog,
    read_entry,
    read_show,
    read_slot,
    register_dog,
    register_handler,
    set_clock,
    setup_class_ready_to_judge,
    setup_completed_class,
    setup_show_with_class,
)
from test_helpers.test_users import (
    headers_with_blank_user_id,
    make_handler_headers,
    make_judge_headers,
    make_sanction_officer_headers,
)


def test_an_unmeasured_agility_dog_is_stopped_before_the_height_comparison():
    """The jump-height rung needs a measurement, so the earlier rung must answer.

    PRD 2.9: "For an `AGILITY` class, the dog's `measurement_status` is not
    `UNMEASURED`, else `ERR_MEASUREMENT_REQUIRED`. This applies to entry creation."

    PRD 2.9: "The jump-height comparison can only be made once a measurement exists, so
    an unmeasured dog entered in an agility class always reports
    `ERR_MEASUREMENT_REQUIRED` and never `ERR_JUMP_HEIGHT_MISMATCH`."

    Design: Corner/validations/unmeasured_agility_dog_is_stopped_before_the_jump_height_check_runs
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=0, class_level="PERFORMANCE", discipline="AGILITY",
        show_overrides={"show_type": "PERFORMANCE"},
        class_overrides={"jump_height_cm": 40},
        judge_overrides={"approved_performance_disciplines": ["AGILITY"]},
    )
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_REQUIRED, 409)

    rows, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"class_id": klass["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert read_dog(dog)["measurement_status"] == "UNMEASURED"


def test_an_entry_filed_on_the_closing_instant_is_still_inside_the_window():
    """The window is inclusive at both ends.

    PRD 3.5: "Entries are accepted only while the show is `APPROVED` — before the day
    opens, in other words — and only while the logical clock lies inside the show's
    entry window, which is inclusive at both ends: the instant equal to `entry_open_at`
    and the instant equal to `entry_close_at` are both inside, and anything outside
    reports `ERR_ENTRY_WINDOW_CLOSED`."

    Design: Corner/validations/entry_created_at_exactly_entry_close_at_is_inside_the_window
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )
    set_clock("2026-09-01T23:59:59Z")

    entry = validate_success(
        api_client.create_entry(
            create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert entry["entry_status"] == "RECEIVED"
    assert_instant_equals(entry["created_at"], "2026-09-01T23:59:59Z", "created_at")
    assert_three_fractional_digits(entry["created_at"], "created_at")
    assert entry["source"] == "HANDLER_SUBMITTED"
    assert entry["promoted_from_entry_id"] is None
    assert entry["armband_number"] is None


def test_a_second_entry_into_a_single_place_class_is_refused():
    """The class gate counts the RECEIVED population the published counter ignores.

    PRD 3.5: "The class's own population, counted across `RECEIVED`, `CONFIRMED`,
    `CHECKED_IN` and `JUDGED`, must remain at or below the class's `entry_limit` once
    this entry is added, else `ERR_CLASS_ENTRY_LIMIT_REACHED`."

    Design: Corner/validations/second_entry_into_a_single_place_class_returns_class_entry_limit_reached
    """
    context = setup_show_with_class(
        num_dogs=2, num_entries=1, class_overrides={"entry_limit": 1}
    )
    show, klass, handler = context["show"], context["klass"], context["handler"]

    response = api_client.create_entry(
        create_entry_payload(
            show["id"], klass["id"], context["dogs"][1]["id"], handler["id"]
        ),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CLASS_ENTRY_LIMIT_REACHED, 409)

    rows, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"class_id": klass["id"]})
    )
    assert len(rows) == 1
    assert meta["total_count"] == 1

    refreshed = read_class(klass)
    assert refreshed["status"] == "OPEN"
    assert refreshed["entry_count"] == 0


def test_an_empty_class_cannot_take_an_entry_once_the_show_cap_is_full():
    """The show-wide cap aggregates across classes, so an empty class is no refuge.

    PRD 3.5: "The show's total population across every class, counted over those same
    four statuses, must likewise remain at or below `max_total_entries`, else
    `ERR_SHOW_ENTRY_CAP_REACHED`."

    Design: Corner/validations/entry_in_a_second_class_returns_show_entry_cap_reached
    """
    context = setup_show_with_class(
        num_dogs=2, num_entries=1, show_overrides={"max_total_entries": 1}
    )
    show, handler = context["show"], context["handler"]
    roomy_class = offer_class(show, class_code="B2")

    response = api_client.create_entry(
        create_entry_payload(
            show["id"], roomy_class["id"], context["dogs"][1]["id"], handler["id"]
        ),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_SHOW_ENTRY_CAP_REACHED, 409)

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"show_id": show["id"]})
    )
    assert meta["total_count"] == 1

    refreshed = read_class(roomy_class)
    assert refreshed["entry_count"] == 0
    assert refreshed["status"] == "OPEN"


def test_the_confirmation_one_dog_past_the_judges_capacity_is_refused():
    """The capacity limit is inclusive, so only the next confirmation fails.

    PRD 3.5: "Counting the entry being confirmed, that load must be at or below the
    slot's `assigned_dog_capacity` — the limit is inclusive, so the confirmation that
    lands exactly on the capacity succeeds and the next one fails with
    `ERR_JUDGE_DOG_LIMIT_EXCEEDED`."

    Design: Corner/validations/confirmation_one_dog_past_the_judge_capacity_returns_judge_dog_limit_exceeded
    """
    context = setup_show_with_class(
        num_dogs=2, judge_overrides={"max_daily_dog_count": 1}
    )
    confirm_entry(context["entries"][0])

    response = api_client.confirm_entry(context["entries"][1]["id"], SS_HEADERS)
    validate_error(response, ApiErrorId.ERR_JUDGE_DOG_LIMIT_EXCEEDED, 409)

    refused = read_entry(context["entries"][1])
    assert refused["entry_status"] == "RECEIVED"
    assert refused["armband_number"] is None
    assert refused["entry_fee_cents"] == 0

    show = read_show(context["show"])
    assert show["confirmed_entry_count"] == 1
    assert show["fee_charged_cents"] == 4663
    assert show["armband_high_water"] == 1


def test_an_unmeasured_dog_is_welcome_in_an_obedience_class():
    """The measuring rules are conditioned on the discipline, not on the class level.

    PRD 3.1: "A class that is not an agility class has no jump height at all and this
    ladder is not consulted for it."

    Design: Corner/validations/unmeasured_dog_enters_an_obedience_class_because_the_measurement_rule_is_agility_only
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=0, class_level="PERFORMANCE", discipline="OBEDIENCE",
        show_overrides={"show_type": "PERFORMANCE"},
    )
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )

    entry = validate_success(
        api_client.create_entry(
            create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert entry["entry_status"] == "RECEIVED"
    assert entry["class_id"] == klass["id"]
    assert entry["welfare_status"] == "CLEAR"

    offered = read_class(klass)
    assert offered["discipline"] == "OBEDIENCE"
    assert offered["jump_height_cm"] is None
    assert read_dog(dog)["measurement_status"] == "UNMEASURED"


def test_a_suspended_handler_cannot_enter_a_dog_at_all():
    """Standing is checked well before any referential rule.

    PRD 2.9: "The relevant handler's `status` is `ACTIVE`, else
    `ERR_HANDLER_SUSPENDED`. This applies to entry creation, entry confirmation and
    protest filing."

    Design: Corner/validations/suspended_handler_cannot_enter_a_dog
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    show, klass, dog = context["show"], context["klass"], context["dogs"][0]
    suspended = register_handler(
        handler_name="Bo Trent", member_number="M-1002", status="SUSPENDED",
        suspension_reason="Unpaid dues for the current season",
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], suspended["id"]),
        make_handler_headers(suspended["id"]),
    )
    validate_error(response, ApiErrorId.ERR_HANDLER_SUSPENDED, 403)

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"show_id": show["id"]})
    )
    assert meta["total_count"] == 0

    unchanged = validate_success(
        api_client.get_handler(suspended["id"], SS_HEADERS), 200
    )
    assert unchanged["status"] == "SUSPENDED"
    assert unchanged["suspension_reason"] == "Unpaid dues for the current season"


def test_the_same_dog_cannot_be_entered_twice_in_one_class():
    """Uniqueness is keyed on the show, the class and the dog, and counts a RECEIVED row.

    PRD 3.5: "The same dog may not hold a second entry in the same class of the same
    show unless the existing one is `WITHDRAWN` or `DISQUALIFIED`; any other existing
    status, including `ABSENT` and `JUDGED`, makes the new entry a duplicate and reports
    `ERR_DUPLICATE_ENTRY`."

    Design: Corner/validations/same_dog_entered_twice_in_one_class_returns_duplicate_entry
    """
    context = setup_show_with_class(num_dogs=1)
    show, klass, handler, dog = (
        context["show"], context["klass"], context["handler"], context["dogs"][0]
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DUPLICATE_ENTRY, 409)

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"class_id": klass["id"]})
    )
    assert meta["total_count"] == 1
    assert read_entry(context["entries"][0])["entry_status"] == "RECEIVED"


def test_a_deposit_one_cent_short_of_the_minimum_is_refused():
    """The deposit rung is the last one in the ladder and the only 402.

    PRD 3.9: "The deposit must be at least 5,000 cents, else
    `ERR_PROTEST_DEPOSIT_INSUFFICIENT` — the one HTTP 402 in the catalogue."

    Design: Corner/validations/protest_deposit_one_cent_short_returns_deposit_insufficient
    """
    context = setup_completed_class(num_dogs=2)
    show, handler = context["show"], context["handler"]

    response = api_client.create_protest(
        create_protest_payload(
            show["id"], context["entries"][1]["id"], handler["id"],
            protest_type="MEASUREMENT",
            statement="Winner appears over height for the class.",
            deposit_cents=4999,
        ),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PROTEST_DEPOSIT_INSUFFICIENT, 402)

    _, meta = validate_paginated(
        api_client.list_protests(SS_HEADERS, params={"show_id": show["id"]})
    )
    assert meta["total_count"] == 0

    klass = read_class(context["klass"])
    assert klass["status"] == "COMPLETED"
    assert klass["base_points"] == 1


def test_a_placement_list_shorter_than_the_ring_is_invalid():
    """The list length is fixed by the present count, so a dog cannot be left out.

    PRD 3.8: "The array must hold exactly as many distinct members as the smaller of 4
    and the class's `present_count`, every member must be a `CHECKED_IN` entry of this
    same class, and no member may be repeated or disqualified."

    Design: Corner/validations/placement_list_shorter_than_the_present_count_returns_placement_set_invalid
    """
    context = setup_class_ready_to_judge(num_dogs=2)

    response = api_client.complete_class(
        context["klass"]["id"],
        complete_class_payload([context["entries"][0]["id"]]),
        make_judge_headers(context["judge"]["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PLACEMENT_SET_INVALID, 409)

    klass = read_class(context["klass"])
    assert klass["status"] == "CLOSED"
    assert klass["completed_at"] is None
    assert klass["base_points"] == 0
    assert klass["counted_dog_count"] == 0

    entry = read_entry(context["entries"][0])
    assert entry["entry_status"] == "CHECKED_IN"
    assert entry["points_awarded"] == 0
    assert entry["placement"] is None


def test_a_puppy_too_young_on_the_show_date_cannot_be_entered():
    """The age is measured against the show date, not against the clock.

    PRD 2.9: "The dog's age in whole months on the show date is at least six, else
    `ERR_DOG_UNDER_MINIMUM_AGE`. This applies to entry creation."

    Design: Corner/validations/puppy_under_six_months_on_the_show_date_returns_dog_under_minimum_age
    """
    context = setup_show_with_class(num_dogs=0, num_entries=0)
    show, klass, handler = context["show"], context["klass"], context["handler"]
    puppy = register_dog(
        handler, registration_number="SR-0009", call_name="Sprig",
        birth_date="2026-05-01",
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], puppy["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DOG_UNDER_MINIMUM_AGE, 409)

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"dog_id": puppy["id"]})
    )
    assert meta["total_count"] == 0

    unchanged = read_dog(puppy)
    assert unchanged["birth_date"] == "2026-05-01"
    assert unchanged["championship_points_total"] == 0


def test_a_permanent_card_cannot_be_measured_over():
    """A permanent card is final for the life of the dog.

    PRD 3.1: "A permanent card is final: once a dog's `measurement_status` is
    `PERMANENT_CARD`, any later measurement of any card type is refused with
    `ERR_MEASUREMENT_LOCKED`."

    Design: Corner/validations/measurement_over_a_permanent_card_returns_measurement_locked
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    judge, dog = context["judge"], context["dogs"][0]
    measure_dog(dog, judge, 35.0, "PERMANENT_CARD")

    response = api_client.record_dog_measurement(
        dog["id"], measurement_payload(40.0, "TEMP_CARD"),
        make_judge_headers(judge["id"]),
    )
    validate_error(response, ApiErrorId.ERR_MEASUREMENT_LOCKED, 409)

    locked = read_dog(dog)
    assert locked["measured_height_cm"] == pytest.approx(35.0, abs=0.01)
    assert locked["measurement_status"] == "PERMANENT_CARD"


def test_an_empty_caller_identifier_is_refused_before_anything_is_resolved():
    """Authentication is the first rung, and the header must be non-empty.

    PRD 2.9: "Both `X-User-ID` and `X-User-Role` are present and non-empty on every
    endpoint, else `ERR_UNAUTHENTICATED`."

    Design: Corner/validations/request_with_an_empty_x_user_id_header_returns_unauthenticated
    """
    context = setup_show_with_class(num_dogs=0, num_entries=0)
    judge = context["judge"]

    response = api_client.get_judge(
        judge["id"], headers_with_blank_user_id("ShowSecretary")
    )
    validate_error(response, ApiErrorId.ERR_UNAUTHENTICATED, 401)
    assert "judge_number" not in (response.json().get("data") or {})

    allowed = validate_success(
        api_client.get_judge(judge["id"], make_sanction_officer_headers()), 200
    )
    assert allowed["judge_number"] == "J-77"


def test_the_entry_that_fills_the_last_place_is_accepted():
    """The cap is at-or-below, so the entry that reaches the limit still goes in.

    PRD 3.5: "The class's own population, counted across `RECEIVED`, `CONFIRMED`,
    `CHECKED_IN` and `JUDGED`, must remain at or below the class's `entry_limit` once
    this entry is added, else `ERR_CLASS_ENTRY_LIMIT_REACHED`."

    Design: Corner/validations/entry_that_lands_exactly_on_the_class_limit_is_accepted
    """
    context = setup_show_with_class(
        num_dogs=2, num_entries=1, class_overrides={"entry_limit": 2}
    )
    show, klass, handler = context["show"], context["klass"], context["handler"]

    entry = validate_success(
        api_client.create_entry(
            create_entry_payload(
                show["id"], klass["id"], context["dogs"][1]["id"], handler["id"]
            ),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert entry["entry_status"] == "RECEIVED"
    assert entry["dog_id"] == context["dogs"][1]["id"]
    assert entry["class_id"] == klass["id"]

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"class_id": klass["id"]})
    )
    assert meta["total_count"] == 2

    refreshed = read_class(klass)
    assert refreshed["entry_count"] == 0
    assert refreshed["status"] == "OPEN"


def test_a_season_declared_bitch_cannot_be_entered_in_another_class():
    """The gate reads the welfare axis of a different entry of the same dog.

    PRD 3.7: "Thereafter that entry may be neither confirmed nor checked in, and no new
    entry may be created for a dog that already holds a season-declared entry at that
    show; both attempts report `ERR_BITCH_IN_SEASON`."

    Design: Corner/validations/dog_with_a_season_declared_entry_cannot_be_entered_in_another_class
    """
    context = setup_show_with_class(
        num_dogs=1, confirm_entries=True, dog_overrides={"sex": "BITCH"}
    )
    show, handler, dog = context["show"], context["handler"], context["dogs"][0]
    declare_season(context["entries"][0], handler)
    second_class = attach_judge(offer_class(show, class_code="B2"), context["slot"])

    response = api_client.create_entry(
        create_entry_payload(show["id"], second_class["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_BITCH_IN_SEASON, 409)

    blocking = read_entry(context["entries"][0])
    assert blocking["welfare_status"] == "SEASON_DECLARED"
    assert blocking["entry_status"] == "WITHDRAWN"

    _, meta = validate_paginated(
        api_client.list_entries(SS_HEADERS, params={"class_id": second_class["id"]})
    )
    assert meta["total_count"] == 0


def test_a_sporting_judge_may_not_be_given_a_hound_class():
    """Licensing is checked across the slot's judge and the class being attached.

    PRD 2.9: "The `group_code` of a `BREED`, `GROUP` or `BEST_IN_SHOW` class being
    assigned appears in the judge's `approved_breed_group_codes`, else
    `ERR_JUDGE_NOT_APPROVED_FOR_GROUP`. This applies to judge assignment to a class."

    Design: Corner/validations/assigning_a_hound_class_to_a_sporting_judge_returns_judge_not_approved_for_group
    """
    context = setup_show_with_class(num_dogs=0, num_entries=0, assign_class=False)
    slot = context["slot"]
    hound_class = offer_class(
        context["show"], class_code="H1", breed_code="BEAGLE", group_code="HOUND"
    )

    response = api_client.assign_judge_to_class(
        hound_class["id"], assign_judge_payload(slot["id"]), SS_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_JUDGE_NOT_APPROVED_FOR_GROUP, 409)

    refreshed = read_class(hound_class)
    assert refreshed["assigned_slot_id"] is None
    assert refreshed["status"] == "OPEN"

    refreshed_slot = read_slot(slot)
    assert refreshed_slot["assigned_class_count"] == 0
    assert refreshed_slot["slot_status"] == "CONFIRMED"
