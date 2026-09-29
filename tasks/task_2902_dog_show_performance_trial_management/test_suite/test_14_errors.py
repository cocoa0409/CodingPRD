"""Every rejection the ladder in PRD 2.9 can be driven to on its own.

Each test drives one error identifier and then proves the refusal left nothing
behind: no row created, no counter moved, no version bumped.
"""

from test_helpers import (
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import assert_instant_equals
from test_helpers.constants import SETUP_CLOCK_INSTANT, TEST_DEFAULTS
from test_helpers.factories import (
    adjudicate_filing_payload,
    assign_judge_payload,
    create_entry_payload,
    create_panel_slot_payload,
    create_performance_run_payload,
    create_protest_payload,
    create_registry_filing_payload,
    create_show_payload,
    decide_protest_payload,
)
from test_helpers.fixtures import (
    apply_for_show,
    approve_show,
    close_entries,
    check_in,
    confirm_entry,
    enter_dog,
    file_protest,
    measure_dog,
    offer_class,
    propose_slot,
    open_day,
    raise_filing,
    read_class,
    read_club,
    read_dog,
    read_entry,
    read_judge,
    read_judge_version,
    read_protest,
    read_show,
    read_slot,
    register_club,
    register_dog,
    register_handler,
    register_judge,
    set_clock,
    setup_completed_class,
    setup_show_ready_for_filing,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import (
    SANCTION_OFFICER_BETA_ID,
    make_club_officer_headers,
    make_handler_headers,
    make_judge_headers,
    make_registry_officer_headers,
    make_sanction_officer_headers,
    make_show_secretary_headers,
)


def _approved_show_with_nothing_attached():
    """A sanctioned show and a roster, with no panel, class or entry yet."""
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    judge = register_judge()
    handler = register_handler()
    show = apply_for_show(club)
    submit_show(show, club)
    approve_show(show)
    return {"club": club, "judge": judge, "handler": handler, "show": show}


def test_show_creation_with_an_unknown_club_id_returns_club_not_found():
    """A body foreign key is resolved before the ownership rule can complain.

    PRD 2.9 rung 5: "Every foreign key supplied in the request body resolves to
    an existing row, checked in the order the endpoint declares its input fields,
    else the corresponding not-found identifier."

    PRD 2.6: "The available identifiers are `ERR_CLUB_NOT_FOUND`,
    `ERR_SHOW_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
    `ERR_CLASS_NOT_FOUND`, `ERR_DOG_NOT_FOUND`, `ERR_HANDLER_NOT_FOUND` and
    `ERR_ENTRY_NOT_FOUND`, again all HTTP 404."

    Design: Corner/errors/show_creation_with_an_unknown_club_id_returns_club_not_found
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()

    response = api_client.create_show(
        create_show_payload(NON_EXISTENT_UUID), make_club_officer_headers(club["id"])
    )
    validate_error(response, "ERR_CLUB_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api_client.list_shows(make_show_secretary_headers(), {"club_id": club["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []
    assert read_club(club)["events_approved_count"] == 0


def test_panel_slot_for_an_unknown_judge_returns_judge_not_found():
    """The unresolvable judge answers before the version pin is ever compared.

    PRD 2.9 rung 5: "Every foreign key supplied in the request body resolves to
    an existing row, checked in the order the endpoint declares its input fields,
    else the corresponding not-found identifier."

    PRD 2.9 rung 9: "`expected_show_version` equals the show's `version` on
    ring-block planning and rescheduling, and `expected_judge_version` equals the
    judge's `version` on panel-slot proposal, else `ERR_STALE_SHOW_VERSION` or
    `ERR_STALE_JUDGE_VERSION` respectively."

    Design: Corner/errors/panel_slot_for_an_unknown_judge_returns_judge_not_found
    """
    context = _approved_show_with_nothing_attached()
    judge_version = read_judge_version(context["judge"])

    response = api_client.create_panel_slot(
        create_panel_slot_payload(
            context["show"]["id"], NON_EXISTENT_UUID, judge_version
        ),
        make_show_secretary_headers(),
    )
    validate_error(response, "ERR_JUDGE_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api_client.list_panel_slots(
            make_show_secretary_headers(), {"show_id": context["show"]["id"]}
        )
    )
    assert meta["total_count"] == 0

    judge = read_judge(context["judge"])
    assert judge["version"] == judge_version
    assert judge["confirmed_slot_count"] == 0


def test_assign_judge_with_an_unknown_slot_id_returns_slot_not_found():
    """An unknown slot is a 404, never the slot-state 409 it would have hit next.

    PRD 2.9 rung 5: "Every foreign key supplied in the request body resolves to
    an existing row, checked in the order the endpoint declares its input fields,
    else the corresponding not-found identifier."

    PRD 2.9 rung 8: "assigning a class to, or publishing a block against, a panel
    slot that is not `CONFIRMED` gives `ERR_SLOT_NOT_CONFIRMED`"

    Design: Corner/errors/assign_judge_with_an_unknown_slot_id_returns_slot_not_found
    """
    context = setup_show_with_class(num_dogs=0, num_entries=0, slot_state=None)
    klass = context["klass"]

    response = api_client.assign_judge_to_class(
        klass["id"], assign_judge_payload(NON_EXISTENT_UUID),
        make_show_secretary_headers(),
    )
    validate_error(response, "ERR_SLOT_NOT_FOUND", 404)

    unchanged = read_class(klass)
    assert unchanged["assigned_slot_id"] is None
    assert unchanged["status"] == "OPEN"
    assert unchanged["version"] == 1


def test_class_read_with_an_unknown_id_returns_class_not_found():
    """A well-authenticated read of nothing is a 404, not an empty 200.

    PRD 2.9 rung 3: "Every path parameter resolves to an existing row, checked
    left to right, else the not-found identifier of the leftmost unresolved
    segment. This applies to every endpoint that has a path parameter."

    PRD 2.6: "Each resource kind has its own not-found identifier:
    `ERR_SHOW_NOT_FOUND`, `ERR_JUDGE_NOT_FOUND`, `ERR_SLOT_NOT_FOUND`,
    `ERR_CLASS_NOT_FOUND`, `ERR_DOG_NOT_FOUND`, `ERR_ENTRY_NOT_FOUND`,
    `ERR_RING_BLOCK_NOT_FOUND`, `ERR_PROTEST_NOT_FOUND` and
    `ERR_FILING_NOT_FOUND`, all HTTP 404."

    Design: Corner/errors/class_read_with_an_unknown_id_returns_class_not_found
    """
    context = _approved_show_with_nothing_attached()
    handler_headers = make_handler_headers(context["handler"]["id"])

    response = api_client.get_class(NON_EXISTENT_UUID, handler_headers)
    error = validate_error(response, "ERR_CLASS_NOT_FOUND", 404)
    assert "class_level" not in error, "an error envelope carries no class payload"

    rows, meta = validate_paginated(
        api_client.list_classes(handler_headers, {"show_id": context["show"]["id"]})
    )
    assert meta["total_count"] == 0
    assert rows == []


def test_entry_naming_an_unknown_handler_returns_handler_not_found():
    """The body handler id outranks the ownership rule that also fails here.

    PRD 2.9 rung 5: "Every foreign key supplied in the request body resolves to
    an existing row, checked in the order the endpoint declares its input fields,
    else the corresponding not-found identifier."

    PRD 2.9 rung 6: "For an entity-backed role, `X-User-ID` equals the identifier
    of the entity the operation acts for, else `ERR_NOT_RESOURCE_OWNER`."

    Design: Corner/errors/entry_naming_an_unknown_handler_returns_handler_not_found
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    show, klass, dog, handler = (
        context["show"], context["klass"], context["dogs"][0], context["handler"]
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], NON_EXISTENT_UUID),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, "ERR_HANDLER_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api_client.list_entries(make_show_secretary_headers(), {"class_id": klass["id"]})
    )
    assert meta["total_count"] == 0
    assert read_class(klass)["entry_count"] == 0


def test_confirming_an_unknown_entry_returns_entry_not_found():
    """The confirm action is nothing but a path id, so resolution decides it.

    PRD 2.9 rung 3: "Every path parameter resolves to an existing row, checked
    left to right, else the not-found identifier of the leftmost unresolved
    segment. This applies to every endpoint that has a path parameter."

    Design: Corner/errors/confirming_an_unknown_entry_returns_entry_not_found
    """
    context = setup_show_with_class(num_dogs=0, num_entries=0)

    response = api_client.confirm_entry(NON_EXISTENT_UUID, make_show_secretary_headers())
    validate_error(response, "ERR_ENTRY_NOT_FOUND", 404)

    show = read_show(context["show"])
    assert show["confirmed_entry_count"] == 0
    assert show["fee_charged_cents"] == 0
    assert show["armband_high_water"] == 0


def test_publishing_an_unknown_ring_block_returns_ring_block_not_found():
    """A bodiless publish against nothing can only fail at path resolution.

    PRD 2.9 rung 3: "Every path parameter resolves to an existing row, checked
    left to right, else the not-found identifier of the leftmost unresolved
    segment. This applies to every endpoint that has a path parameter."

    PRD 2.4: "On creation, `updated_at` equals `created_at` and `version` is 1."

    Design: Corner/errors/publishing_an_unknown_ring_block_returns_ring_block_not_found
    """
    context = _approved_show_with_nothing_attached()

    response = api_client.publish_ring_block(
        NON_EXISTENT_UUID, make_show_secretary_headers()
    )
    validate_error(response, "ERR_RING_BLOCK_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api_client.list_ring_blocks(
            make_show_secretary_headers(), {"show_id": context["show"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_show(context["show"])["version"] == 3


def test_protest_read_with_an_unknown_id_returns_protest_not_found():
    """An unknown protest is a 404 while the filtered list is an empty 200.

    PRD 2.9 rung 3: "Every path parameter resolves to an existing row, checked
    left to right, else the not-found identifier of the leftmost unresolved
    segment. This applies to every endpoint that has a path parameter."

    Design: Corner/errors/protest_read_with_an_unknown_id_returns_protest_not_found
    """
    context = _approved_show_with_nothing_attached()
    officer_headers = make_registry_officer_headers()

    response = api_client.get_protest(NON_EXISTENT_UUID, officer_headers)
    validate_error(response, "ERR_PROTEST_NOT_FOUND", 404)

    rows, meta = validate_paginated(
        api_client.list_protests(officer_headers, {"show_id": context["show"]["id"]})
    )
    assert meta["total_count"] == 0
    assert meta["has_more"] is False
    assert isinstance(rows, list) and rows == []


def test_adjudicating_an_unknown_filing_returns_filing_not_found():
    """The registry resolves its own path ids before any filing rule runs.

    PRD 2.9 rung 3: "Every path parameter resolves to an existing row, checked
    left to right, else the not-found identifier of the leftmost unresolved
    segment. This applies to every endpoint that has a path parameter."

    Design: Corner/errors/adjudicating_an_unknown_filing_returns_filing_not_found
    """
    context = _approved_show_with_nothing_attached()
    officer_headers = make_registry_officer_headers()

    response = api_client.adjudicate_registry_filing(
        NON_EXISTENT_UUID, adjudicate_filing_payload("ACCEPT"), officer_headers
    )
    validate_error(response, "ERR_FILING_NOT_FOUND", 404)

    _, meta = validate_paginated(
        api_client.list_show_registry_filings(context["show"]["id"], officer_headers)
    )
    assert meta["total_count"] == 0
    assert read_show(context["show"])["status"] == "APPROVED"


def test_entry_against_a_submitted_show_returns_show_not_accepting_entries():
    """The class is legitimately OPEN, so only the show's status is wrong.

    PRD 3.5: "Entries are accepted only while the show is `APPROVED` — before the
    day opens, in other words — and only while the logical clock lies inside the
    show's entry window, which is inclusive at both ends: the instant equal to
    `entry_open_at` and the instant equal to `entry_close_at` are both inside, and
    anything outside reports `ERR_ENTRY_WINDOW_CLOSED`."

    PRD 2.9 rung 8: "creating an entry, panel slot, class or ring block against a
    show that is not in the status that operation requires gives
    `ERR_SHOW_NOT_ACCEPTING_ENTRIES`"

    Design: Corner/errors/entry_against_a_submitted_show_returns_show_not_accepting_entries
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club()
    handler = register_handler()
    show = apply_for_show(club)
    submit_show(show, club)
    klass = offer_class(show)
    dog = register_dog(handler, index=0)

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, "ERR_SHOW_NOT_ACCEPTING_ENTRIES", 409)

    unchanged = read_class(klass)
    assert unchanged["status"] == "OPEN"
    assert unchanged["entry_count"] == 0
    assert read_show(show)["status"] == "SUBMITTED"

    _, meta = validate_paginated(
        api_client.list_entries(make_show_secretary_headers(), {"show_id": show["id"]})
    )
    assert meta["total_count"] == 0


def test_deciding_a_protest_before_review_begins_returns_protest_not_in_review():
    """A decision is declared only from `UNDER_REVIEW`, so `FILED` is refused.

    PRD 3.9: "A newly filed protest has `status` `FILED`, `review_round` 0 and
    `deposit_refunded` false."

    PRD 2.9 rung 8: "requesting evidence or deciding a protest that is not
    `UNDER_REVIEW`, or resubmitting evidence on one that is not
    `EVIDENCE_REQUESTED`, gives `ERR_PROTEST_NOT_IN_REVIEW`"

    Design: Corner/errors/deciding_a_protest_before_review_begins_returns_protest_not_in_review
    """
    context = setup_completed_class(num_dogs=2)
    target = context["entries"][1]
    protest = file_protest(
        context["show"], target, context["handler"],
        protest_type="MEASUREMENT",
        statement="Winner appears over height.",
        deposit_cents=5000,
    )
    assert protest["status"] == "FILED"

    response = api_client.decide_protest(
        protest["id"],
        decide_protest_payload("UPHOLD", "VACATE_PLACEMENT"),
        make_sanction_officer_headers(SANCTION_OFFICER_BETA_ID),
    )
    validate_error(response, "ERR_PROTEST_NOT_IN_REVIEW", 409)

    unchanged = read_protest(protest)
    assert unchanged["status"] == "FILED"
    assert unchanged["review_round"] == 0
    assert unchanged["resolution_code"] is None
    assert unchanged["decided_at"] is None

    entry = read_entry(target)
    assert entry["placement"] == 2
    assert entry["entry_status"] == "JUDGED"


def test_show_creation_for_a_suspended_club_returns_club_not_active():
    """A suspended club cannot even draft a show, headroom or not.

    PRD 3.2: "If the hosting club's `sanction_status` is anything other than
    `ACTIVE`, the creation is refused with `ERR_CLUB_NOT_ACTIVE`."

    PRD 2.9 rung 14: "The hosting club's `sanction_status` is `ACTIVE` when a show
    application is created or submitted, and the judge's `status` is `ACTIVE` when
    a panel slot is proposed or a class is assigned to that judge's slot, else
    `ERR_CLUB_NOT_ACTIVE` or `ERR_JUDGE_NOT_ACTIVE` respectively."

    Design: Corner/errors/show_creation_for_a_suspended_club_returns_club_not_active
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club(
        name="Lakeside Kennel Club",
        club_code="LSKC",
        annual_event_allowance=2,
        sanction_status="SUSPENDED",
        sanction_note="Late filing of last season accounts",
    )

    response = api_client.create_show(
        create_show_payload(
            club["id"],
            show_name="Lakeside Winter",
            show_date="2026-11-14",
            venue_name="Lakeside Arena",
            entry_open_at="2026-10-01T00:00:00Z",
            entry_close_at="2026-11-01T23:59:59Z",
            max_total_entries=80,
        ),
        make_club_officer_headers(club["id"]),
    )
    validate_error(response, "ERR_CLUB_NOT_ACTIVE", 409)

    _, meta = validate_paginated(
        api_client.list_shows(make_show_secretary_headers(), {"club_id": club["id"]})
    )
    assert meta["total_count"] == 0

    unchanged = read_club(club)
    assert unchanged["sanction_status"] == "SUSPENDED"
    assert unchanged["events_approved_count"] == 0


def test_panel_slot_for_a_provisional_judge_returns_judge_not_active():
    """The gate is `ACTIVE`, so a fully licensed PROVISIONAL judge is refused too.

    PRD 3.1: "The licence `status` defaults to `ACTIVE`, and only an `ACTIVE`
    judge may be proposed for a panel."

    PRD 3.3: "The judge's `status` must be `ACTIVE`, else `ERR_JUDGE_NOT_ACTIVE`."

    Design: Corner/errors/panel_slot_for_a_provisional_judge_returns_judge_not_active
    """
    context = _approved_show_with_nothing_attached()
    provisional = register_judge(
        judge_number="J-79", full_name="Iris Bell", status="PROVISIONAL"
    )
    provisional_version = provisional["version"]

    response = api_client.create_panel_slot(
        create_panel_slot_payload(
            context["show"]["id"], provisional["id"], provisional_version
        ),
        make_show_secretary_headers(),
    )
    validate_error(response, "ERR_JUDGE_NOT_ACTIVE", 409)

    unchanged = read_judge(provisional)
    assert unchanged["status"] == "PROVISIONAL"
    assert unchanged["confirmed_slot_count"] == 0
    assert unchanged["version"] == provisional_version

    _, meta = validate_paginated(
        api_client.list_panel_slots(
            make_show_secretary_headers(), {"show_id": context["show"]["id"]}
        )
    )
    assert meta["total_count"] == 0


def test_assigning_an_agility_class_to_an_obedience_only_judge_returns_discipline_not_approved():
    """Performance licensing is per discipline, not per panel role.

    PRD 2.9 rung 16: "The `discipline` of a `PERFORMANCE` class being assigned
    appears in the judge's `approved_performance_disciplines`, else
    `ERR_JUDGE_NOT_APPROVED_FOR_DISCIPLINE`. This applies to judge assignment to a
    class."

    PRD 3.3: "a `PERFORMANCE_JUDGE` slot requires the judge's
    `approved_performance_disciplines` to be non-empty."

    Design: Corner/errors/assigning_an_agility_class_to_an_obedience_only_judge_returns_discipline_not_approved
    """
    context = setup_show_with_class(
        num_dogs=0,
        num_entries=0,
        judge_overrides={"approved_performance_disciplines": ["OBEDIENCE"]},
        show_overrides={"show_type": "PERFORMANCE"},
        class_level="PERFORMANCE",
        discipline="AGILITY",
        class_overrides={"class_code": "A1", "jump_height_cm": 40},
        assign_class=False,
    )
    klass, slot = context["klass"], context["slot"]

    response = api_client.assign_judge_to_class(
        klass["id"], assign_judge_payload(slot["id"]), make_show_secretary_headers()
    )
    validate_error(response, "ERR_JUDGE_NOT_APPROVED_FOR_DISCIPLINE", 409)

    assert read_class(klass)["assigned_slot_id"] is None
    unchanged_slot = read_slot(slot)
    assert unchanged_slot["assigned_class_count"] == 0
    assert unchanged_slot["slot_status"] == "CONFIRMED"


def test_beagle_entered_in_a_golden_retriever_class_returns_breed_mismatch():
    """A BREED class is single-breed, so the comparison is a hard gate.

    PRD 2.9 rung 19: "The dog's `breed_code` equals the class's `breed_code` for a
    `BREED` class, and the dog's `group_code` equals the class's `group_code` for a
    `GROUP` class, else `ERR_BREED_MISMATCH`. This applies to entry creation."

    Design: Corner/errors/beagle_entered_in_a_golden_retriever_class_returns_breed_mismatch
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=0,
        dog_overrides={"breed_code": "BEAGLE", "group_code": "HOUND"},
    )
    show, klass, dog, handler = (
        context["show"], context["klass"], context["dogs"][0], context["handler"]
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, "ERR_BREED_MISMATCH", 409)

    _, meta = validate_paginated(
        api_client.list_entries(make_show_secretary_headers(), {"class_id": klass["id"]})
    )
    assert meta["total_count"] == 0

    unchanged_dog = read_dog(dog)
    assert unchanged_dog["breed_code"] == "BEAGLE"
    assert unchanged_dog["group_code"] == "HOUND"


def _agility_show_with_a_measured_dog(jump_height_cm=30, measured_height_cm=35.0):
    """A performance show whose agility class is judged by an agility licensee."""
    context = setup_show_with_class(
        num_dogs=1,
        num_entries=0,
        judge_overrides={"approved_performance_disciplines": ["AGILITY"]},
        show_overrides={"show_type": "PERFORMANCE"},
        class_level="PERFORMANCE",
        discipline="AGILITY",
        class_overrides={"class_code": "A1", "jump_height_cm": jump_height_cm},
    )
    context["dogs"][0] = measure_dog(
        context["dogs"][0], context["judge"], measured_height_cm, "TEMP_CARD"
    )
    return context


def test_measured_dog_entered_in_the_wrong_jump_class_returns_jump_height_mismatch():
    """The card exists, so the mapping runs and the mapping is what refuses.

    PRD 3.1: "The bounds are inclusive at the top of each band, so exactly 35.0 cm
    maps to the 30 cm height while 35.1 cm maps to 40 cm."

    PRD 2.9 rung 21: "For an `AGILITY` class, the class's `jump_height_cm` equals
    the height the dog's `measured_height_cm` maps to, else
    `ERR_JUMP_HEIGHT_MISMATCH`. This applies to entry creation."

    Design: Corner/errors/measured_dog_entered_in_the_wrong_jump_class_returns_jump_height_mismatch
    """
    context = _agility_show_with_a_measured_dog(jump_height_cm=40)
    show, klass, dog, handler = (
        context["show"], context["klass"], context["dogs"][0], context["handler"]
    )

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, "ERR_JUMP_HEIGHT_MISMATCH", 409)

    unchanged = read_dog(dog)
    assert unchanged["measured_height_cm"] == 35.0
    assert unchanged["measurement_status"] == "TEMP_CARD"

    _, meta = validate_paginated(
        api_client.list_entries(make_show_secretary_headers(), {"class_id": klass["id"]})
    )
    assert meta["total_count"] == 0


def test_agility_course_faster_than_the_yardage_minimum_returns_course_design_invalid():
    """A 150 m course cannot carry a 20 s standard time.

    PRD 3.8: "anything else reports `ERR_COURSE_DESIGN_INVALID`, as does an
    agility course whose `standard_course_time_s` is below the yardage-derived
    floor of the course length in metres divided by 5.0 metres per second and
    rounded up to the next whole second."

    Design: Corner/errors/agility_course_faster_than_the_yardage_minimum_returns_course_design_invalid
    """
    context = _agility_show_with_a_measured_dog(jump_height_cm=30)
    show, klass, dog, handler, judge = (
        context["show"], context["klass"], context["dogs"][0],
        context["handler"], context["judge"],
    )
    entry = confirm_entry(enter_dog(show, klass, dog, handler))
    close_entries(klass)
    open_day(show)
    entry = check_in(entry, "PRESENT")

    response = api_client.create_performance_run(
        create_performance_run_payload(
            entry["id"], 150.0, 20.0, 19.0, faults_count=0, refusals_count=0
        ),
        make_judge_headers(judge["id"]),
    )
    validate_error(response, "ERR_COURSE_DESIGN_INVALID", 409)

    _, meta = validate_paginated(
        api_client.list_entry_performance_runs(
            entry["id"], make_judge_headers(judge["id"])
        )
    )
    assert meta["total_count"] == 0
    assert read_entry(entry)["entry_status"] == "CHECKED_IN"


def test_entry_one_second_after_the_window_closes_returns_entry_window_closed():
    """`entry_close_at` is inclusive, so the refusal starts one second later.

    PRD 3.5: "only while the logical clock lies inside the show's entry window,
    which is inclusive at both ends: the instant equal to `entry_open_at` and the
    instant equal to `entry_close_at` are both inside, and anything outside reports
    `ERR_ENTRY_WINDOW_CLOSED`."

    Design: Corner/errors/entry_one_second_after_the_window_closes_returns_entry_window_closed
    """
    context = setup_show_with_class(num_dogs=1, num_entries=0)
    show, klass, dog, handler = (
        context["show"], context["klass"], context["dogs"][0], context["handler"]
    )
    assert_instant_equals(
        read_show(show)["entry_close_at"], TEST_DEFAULTS["ENTRY_CLOSE_AT"],
        "show.entry_close_at",
    )
    set_clock("2026-09-02T00:00:00Z")

    response = api_client.create_entry(
        create_entry_payload(show["id"], klass["id"], dog["id"], handler["id"]),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, "ERR_ENTRY_WINDOW_CLOSED", 409)

    unchanged = read_class(klass)
    assert unchanged["status"] == "OPEN"
    assert unchanged["entry_count"] == 0

    _, meta = validate_paginated(
        api_client.list_entries(make_show_secretary_headers(), {"show_id": show["id"]})
    )
    assert meta["total_count"] == 0


def test_protest_one_second_past_the_window_returns_protest_window_expired():
    """The 24-hour window is inclusive, so 24 hours and one second is closed.

    PRD 3.9: "When the protested entry's class has reached `COMPLETED` or
    `ABANDONED`, the window runs for 24 hours from that class's `completed_at` and
    the comparison is inclusive, so a filing at exactly 24 hours after completion
    is accepted and one second later is not."

    Design: Corner/errors/protest_one_second_past_the_window_returns_protest_window_expired
    """
    context = setup_completed_class(num_dogs=2)
    target = context["entries"][1]
    set_clock("2026-09-13T10:00:01Z")

    response = api_client.create_protest(
        create_protest_payload(
            context["show"]["id"], target["id"], context["handler"]["id"],
            protest_type="MEASUREMENT",
            statement="Winner appears over height.",
            deposit_cents=5000,
        ),
        make_handler_headers(context["handler"]["id"]),
    )
    validate_error(response, "ERR_PROTEST_WINDOW_EXPIRED", 409)

    _, meta = validate_paginated(
        api_client.list_protests(
            make_show_secretary_headers(), {"show_id": context["show"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert_instant_equals(
        read_class(context["klass"])["completed_at"], "2026-09-12T10:00:00Z",
        "class.completed_at",
    )


def test_fourth_slot_for_the_same_judge_at_one_show_returns_judge_assignment_limit():
    """Three PROPOSED slots already fill the per-show limit.

    PRD 3.3: "A judge may hold at most three slots at one show counting those in
    `PROPOSED` and `CONFIRMED` together, and a judge may work at most one show on
    any given `show_date` — so no proposal may be made for a judge who already holds
    a `CONFIRMED` slot at a different show whose `show_date` equals this show's."

    PRD 2.9 rung 30: "The judge's per-show and per-day slot limits hold, else
    `ERR_JUDGE_ASSIGNMENT_LIMIT`. This applies to panel-slot proposal."

    Design: Corner/errors/fourth_slot_for_the_same_judge_at_one_show_returns_judge_assignment_limit
    """
    context = _approved_show_with_nothing_attached()
    show, judge = context["show"], context["judge"]
    for role in ("BREED_JUDGE", "GROUP_JUDGE", "BIS_JUDGE"):
        propose_slot(show, judge, panel_role=role)
    judge_version = read_judge_version(judge)

    response = api_client.create_panel_slot(
        create_panel_slot_payload(show["id"], judge["id"], judge_version),
        make_show_secretary_headers(),
    )
    validate_error(response, "ERR_JUDGE_ASSIGNMENT_LIMIT", 409)

    rows, meta = validate_paginated(
        api_client.list_panel_slots(
            make_show_secretary_headers(),
            {"show_id": show["id"], "judge_id": judge["id"]},
        )
    )
    assert meta["total_count"] == 3
    for row in rows:
        assert row["slot_status"] == "PROPOSED"
        assert row["assigned_class_count"] == 0

    unchanged = read_judge(judge)
    assert unchanged["version"] == judge_version
    assert unchanged["confirmed_slot_count"] == 0


def test_second_registry_filing_while_one_is_pending_returns_filing_already_open():
    """Only a rejected filing clears the way for a replacement.

    PRD 3.9: "A filing may be raised only when the show's `status` is `COMPLETED`,
    when every class of the show has reached `COMPLETED` or `ABANDONED` (otherwise
    `ERR_CLASSES_NOT_COMPLETE`), when no protest of the show is still `FILED`,
    `UNDER_REVIEW` or `EVIDENCE_REQUESTED` (otherwise
    `ERR_OPEN_PROTEST_BLOCKS_FILING`), and when the show holds no existing filing
    whose `filing_status` is `PENDING` or `ACCEPTED` (otherwise
    `ERR_FILING_ALREADY_OPEN`)."

    Design: Corner/errors/second_registry_filing_while_one_is_pending_returns_filing_already_open
    """
    context = setup_show_ready_for_filing(num_dogs=1)
    first = raise_filing(context["show"])
    assert first["filing_status"] == "PENDING"

    response = api_client.create_registry_filing(
        create_registry_filing_payload(context["show"]["id"]),
        make_show_secretary_headers(),
    )
    validate_error(response, "ERR_FILING_ALREADY_OPEN", 409)

    rows, meta = validate_paginated(
        api_client.list_show_registry_filings(
            context["show"]["id"], make_registry_officer_headers()
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == first["id"]
    assert rows[0]["filing_status"] == "PENDING"
    assert rows[0]["amendment_count"] == 0
    assert read_show(context["show"])["status"] == "COMPLETED"


def test_submitting_a_second_show_on_a_one_event_allowance_returns_allowance_exhausted():
    """Approval spends the allowance, so the second show dies at submission.

    PRD 3.2: "the club's `events_approved_count` must be strictly less than its
    `annual_event_allowance` — an equal count means the allowance is spent and the
    submission is refused with `ERR_CLUB_ALLOWANCE_EXHAUSTED`."

    PRD 3.1: "it starts at 0 and is thereafter always the number of shows of that
    club whose `status` is `APPROVED`, `IN_PROGRESS`, `COMPLETED` or
    `RESULTS_FILED`."

    Design: Corner/errors/submitting_a_second_show_on_a_one_event_allowance_returns_allowance_exhausted
    """
    set_clock(SETUP_CLOCK_INSTANT)
    club = register_club(annual_event_allowance=1)
    first = apply_for_show(club)
    submit_show(first, club)
    approve_show(first)

    second = validate_success(
        api_client.create_show(
            create_show_payload(
                club["id"],
                show_name="Autumn Classic II",
                show_date="2026-10-10",
                entry_open_at="2026-09-05T00:00:00Z",
                entry_close_at="2026-10-01T23:59:59Z",
            ),
            make_club_officer_headers(club["id"]),
        ),
        201,
    )

    response = api_client.submit_show(
        second["id"], make_club_officer_headers(club["id"])
    )
    validate_error(response, "ERR_CLUB_ALLOWANCE_EXHAUSTED", 409)

    unchanged = read_show(second)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["submitted_at"] is None
    assert unchanged["revision_count"] == 0
    assert unchanged["version"] == 1

    unchanged_club = read_club(club)
    assert unchanged_club["events_approved_count"] == 1
    assert unchanged_club["annual_event_allowance"] == 1
