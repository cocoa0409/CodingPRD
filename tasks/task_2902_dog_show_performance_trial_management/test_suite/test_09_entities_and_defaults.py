"""Resource shapes at the moment of creation and retrieval: declared defaults,
zeroed roll-ups, ignored system fields, flat parentage and the append-only run."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_dog,
    assert_judge,
    assert_performance_run,
    assert_show,
)
from test_helpers.factories import (
    assign_judge_payload,
    create_breed_class_payload,
    create_club_payload,
    create_dog_payload,
    create_entry_payload,
    create_group_class_payload,
    create_show_payload,
)
from test_helpers.fixtures import (
    SO_HEADERS,
    SS_HEADERS,
    apply_for_show,
    approve_show,
    confirmed_slot,
    enter_dog,
    offer_class,
    read_class,
    read_slot,
    record_run,
    register_club,
    register_handler,
    register_judge,
    set_clock,
    setup_show_with_class,
    submit_show,
)
from test_helpers.test_users import make_club_officer_headers, make_handler_headers


def test_a_new_show_application_returns_a_fully_zeroed_ledger():
    """Every money and points counter starts at 0 and the advisory starts as null.

    PRD: "A show is created with `status` `DRAFT`, `revision_count` 0,
    `armband_high_water` 0, every money and points counter at 0,
    `temperature_reading_count` 0, and `current_heat_index_c` and
    `current_advisory_level` both null until the first temperature reading arrives."

    Design: Corner/entities/show_creation_returns_draft_with_zeroed_ledger_counters
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()

    show = validate_success(
        api_client.create_show(
            create_show_payload(club["id"]), make_club_officer_headers(club["id"])
        ),
        201,
    )
    assert_show(show)
    assert show["status"] == "DRAFT"
    assert show["revision_count"] == 0
    assert show["armband_high_water"] == 0
    for field in (
        "fee_charged_cents", "fee_refunded_cents", "fee_retained_cents",
        "fee_collected_cents", "levy_total_cents",
    ):
        assert show[field] == 0, f"{field} must start at 0"
    assert show["confirmed_entry_count"] == 0
    assert show["points_awarded_total"] == 0
    assert show["temperature_reading_count"] == 0
    assert show["current_advisory_level"] is None
    assert show["current_heat_index_c"] is None
    assert show["club_id"] == club["id"]
    assert show["championship_points_scale"] == "SCALE_A"


def test_reading_a_judge_echoes_the_licence_and_the_version_a_proposal_must_pin():
    """The judge read is the channel a panel proposal takes its pinned version from.

    PRD: "A judge's `confirmed_slot_count` is a derived figure, initialised to 0 and
    thereafter always the number of that judge's panel slots whose `slot_status` is
    `CONFIRMED`."

    Design: Corner/entities/judge_retrieval_exposes_version_for_occ_pinning
    """
    set_clock("2026-08-10T09:00:00Z")
    created = register_judge()

    judge = validate_success(api_client.get_judge(created["id"], SS_HEADERS), 200)
    assert_judge(judge)
    assert judge["judge_number"] == "J-77"
    assert judge["full_name"] == "Rex Calder"
    assert judge["approved_breed_group_codes"] == ["SPORTING"]
    assert judge["approved_performance_disciplines"] == ["OBEDIENCE"]
    assert judge["max_daily_dog_count"] == 175
    assert judge["status"] == "ACTIVE"
    assert judge["confirmed_slot_count"] == 0
    assert judge["version"] == created["version"]


def test_a_class_filter_and_a_page_window_compose_on_one_entry_listing():
    """`total_count` counts the filtered population before the window is applied.

    PRD: "The `meta` block of a list response carries `limit` and `offset` as they
    were applied, `total_count` as the number of rows matching the filters before the
    window was applied, and `has_more` as true exactly when rows remain beyond the
    returned window."

    Design: Corner/entities/entries_listing_filters_by_class_and_paginates
    """
    context = setup_show_with_class(num_dogs=3, class_overrides={"class_code": "B1"})
    show, handler = context["show"], context["handler"]
    other_class = offer_class(show, class_level="BREED", class_code="B2")
    outsider = enter_dog(show, other_class, context["dogs"][0], handler)

    rows, meta = validate_paginated(
        api_client.list_entries(
            SS_HEADERS,
            {
                "show_id": show["id"],
                "class_id": context["klass"]["id"],
                "limit": 2,
                "offset": 0,
            },
        )
    )
    assert meta["total_count"] == 3
    assert meta["has_more"] is True
    assert len(rows) == 2
    assert all(row["class_id"] == context["klass"]["id"] for row in rows)
    assert outsider["id"] not in [row["id"] for row in rows]
    assert all(row["entry_status"] == "RECEIVED" for row in rows)
    assert all(row["armband_number"] is None for row in rows)


def test_reading_a_show_that_does_not_exist_reports_the_show_not_found_identifier():
    """Path existence is settled before anything about the body or the role.

    PRD: "Every path parameter resolves to an existing row, checked left to right,
    else the not-found identifier of the leftmost unresolved segment."

    Design: Corner/entities/show_get_with_unknown_id_returns_show_not_found
    """
    set_clock("2026-08-10T09:00:00Z")

    response = api_client.get_show(NON_EXISTENT_UUID, SS_HEADERS)
    validate_error(response, ApiErrorId.ERR_SHOW_NOT_FOUND, 404)


def test_an_application_without_a_show_type_is_a_shape_violation_and_persists_nothing():
    """A missing required field is rejected before any downstream rule is consulted.

    PRD: "The request body carries every required field with the declared type, every
    enum field carries a declared member, integer money and count fields are not
    negative, `limit` is between 1 and 100 inclusive and `offset` is not negative,
    else `ERR_INVALID_REQUEST`."

    Design: Corner/entities/show_creation_missing_required_show_type_returns_invalid_request
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()

    payload = create_show_payload(club["id"])
    del payload["show_type"]
    response = api_client.create_show(payload, make_club_officer_headers(club["id"]))
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)

    _, meta = validate_paginated(
        api_client.list_shows(SS_HEADERS, {"club_id": club["id"]})
    )
    assert meta["total_count"] == 0


def test_a_club_registered_without_its_optional_fields_takes_the_declared_defaults():
    """Standing, allowance and note each have a declared default, not a null.

    PRD: "The officer may also state the club's `sanction_status`, which defaults to
    `ACTIVE`, and an `annual_event_allowance`, which defaults to 2 and may not be
    negative; the allowance caps how many of the club's shows may reach `APPROVED` or
    beyond in the calendar year of their `show_date`."

    Design: Corner/entities/club_creation_omitting_optionals_applies_declared_defaults
    """
    set_clock("2026-08-10T09:00:00Z")

    payload = create_club_payload(
        name="Lakeshore Kennel Club", club_code="LKSC", region_code="MW"
    )
    del payload["annual_event_allowance"]
    club = validate_success(api_client.create_club(payload, SO_HEADERS), 201)

    assert club["sanction_status"] == "ACTIVE"
    assert club["annual_event_allowance"] == 2
    assert club["sanction_note"] is None
    assert club["events_approved_count"] == 0


def test_a_dog_registered_with_a_points_total_in_the_body_still_starts_from_zero():
    """The four competitive roll-ups are maintained by workflows, never written directly.

    PRD: "A freshly registered dog begins with `measurement_status` set to
    `UNMEASURED` and no `measured_height_cm`, with `championship_points_total` and
    `majors_count` at 0, with `qualifying_leg_counts` holding zero legs for each of
    the three disciplines, and with an empty `title_codes` list."

    Design: Corner/entities/dog_creation_extra_computed_points_field_input_ignored
    """
    set_clock("2026-08-10T09:00:00Z")
    handler = register_handler()

    dog = validate_success(
        api_client.create_dog(
            create_dog_payload(handler["id"], championship_points_total=99),
            make_handler_headers(handler["id"]),
        ),
        201,
    )
    assert_dog(dog)
    assert dog["championship_points_total"] == 0
    assert dog["majors_count"] == 0
    assert dog["qualifying_leg_counts"] == {"AGILITY": 0, "OBEDIENCE": 0, "RALLY": 0}
    assert dog["title_codes"] == []
    assert dog["measurement_status"] == "UNMEASURED"
    assert dog["measured_height_cm"] is None


def test_an_application_that_posts_its_own_status_is_still_created_in_draft():
    """A server-owned field supplied by a caller is ignored, not honoured.

    PRD: "Unknown extra body fields are ignored rather than rejected."

    Design: Corner/entities/show_creation_status_field_input_ignored
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()

    show = validate_success(
        api_client.create_show(
            create_show_payload(club["id"], status="APPROVED"),
            make_club_officer_headers(club["id"]),
        ),
        201,
    )
    assert show["status"] == "DRAFT"
    assert show["approved_by_user_id"] is None
    assert show["approval_decided_at"] is None
    assert show["submitted_at"] is None
    assert_show(show)


def test_an_application_naming_a_show_type_outside_the_closed_set_is_refused():
    """The enum is checked in the shape band, well before any pairing rule.

    PRD: "a show's `show_type`, one of `CONFORMATION`, `PERFORMANCE` or `COMBINED`"

    Design: Corner/entities/show_creation_with_undeclared_show_type_returns_invalid_request
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()

    response = api_client.create_show(
        create_show_payload(club["id"], show_type="JUNIOR_SHOWMANSHIP"),
        make_club_officer_headers(club["id"]),
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST, 400)


def test_a_recorded_run_is_listed_without_a_version_or_an_updated_at():
    """The run is the one resource that exposes only `id` and `created_at`.

    PRD: "Runs are append-only score sheets: once written they are never edited, so a
    run exposes only `id` and `created_at`. It has no `updated_at` field and no
    `version` field at all, and callers must not expect either."

    Design: Corner/entities/performance_run_row_carries_no_version_or_update_surface
    """
    context = setup_show_with_class(
        num_dogs=1,
        confirm_entries=True,
        close_class=True,
        open_show=True,
        check_in_attendance="PRESENT",
        class_level="PERFORMANCE",
        discipline="OBEDIENCE",
        show_overrides={"show_type": "PERFORMANCE"},
        class_overrides={"class_code": "P1"},
    )
    record_run(
        context["entries"][0], context["judge"],
        course_yardage_m=100.0, standard_course_time_s=90.0, actual_time_s=60.0,
        obedience_deductions=12.0,
    )

    rows, meta = validate_paginated(
        api_client.list_entry_performance_runs(
            context["entries"][0]["id"], SS_HEADERS, {"limit": 10, "offset": 0}
        )
    )
    assert meta["total_count"] == 1
    run = rows[0]
    assert_performance_run(run)
    assert run["discipline"] == "OBEDIENCE"
    assert float(run["final_score"]) == 188.0
    assert run["run_result"] == "QUALIFIED"
    assert run["title_leg_awarded"] is True
    assert float(run["time_faults"]) == 0.0
    assert float(run["total_faults"]) == 12.0


def test_an_entry_naming_a_dog_that_does_not_exist_reports_the_dog_not_found_identifier():
    """Parentage travels in the body, so an unresolvable dog is a body reference failure.

    PRD: "Every foreign key supplied in the request body resolves to an existing row,
    checked in the order the endpoint declares its input fields, else the
    corresponding not-found identifier."

    Design: Corner/entities/entry_creation_with_unknown_dog_id_returns_dog_not_found
    """
    context = setup_show_with_class(num_dogs=0, class_overrides={"class_code": "B1"})
    handler = context["handler"]

    response = api_client.create_entry(
        create_entry_payload(
            context["show"]["id"], context["klass"]["id"],
            NON_EXISTENT_UUID, handler["id"],
        ),
        make_handler_headers(handler["id"]),
    )
    validate_error(response, ApiErrorId.ERR_DOG_NOT_FOUND, 404)
    assert read_class(context["klass"])["entry_count"] == 0


def test_a_class_may_not_borrow_a_confirmed_slot_from_another_show():
    """The slot must belong to the same show as the class it is attached to.

    PRD: "And the slot's `panel_role` must pair with the class's `class_level`
    exactly — `BREED_JUDGE` with `BREED`, `GROUP_JUDGE` with `GROUP`, `BIS_JUDGE`
    with `BEST_IN_SHOW`, `PERFORMANCE_JUDGE` with `PERFORMANCE` — while the slot must
    also belong to the same show as the class; either failure reports
    `ERR_PANEL_ROLE_MISMATCH`."

    Design: Corner/entities/assign_judge_with_slot_from_another_show_returns_panel_role_mismatch
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()
    register_handler()
    register_judge()
    second_judge = register_judge(judge_number="J-78", full_name="Vera Lund")

    first = apply_for_show(club)
    submit_show(first, club)
    approve_show(first)

    second = apply_for_show(club, show_name="Spring Trial", show_date="2026-09-19")
    submit_show(second, club)
    approve_show(second)
    foreign_slot = confirmed_slot(second, second_judge, panel_role="BREED_JUDGE")

    klass = offer_class(first, class_level="BREED", class_code="B1")
    response = api_client.assign_judge_to_class(
        klass["id"], assign_judge_payload(foreign_slot["id"]), SS_HEADERS
    )
    validate_error(response, ApiErrorId.ERR_PANEL_ROLE_MISMATCH, 409)

    assert read_class(klass)["assigned_slot_id"] is None
    assert read_slot(foreign_slot)["assigned_class_count"] == 0


def test_a_class_may_not_advance_into_a_parent_class_of_another_show():
    """The advancement chain never crosses a show boundary.

    PRD: "Any other pairing — a wrong rung, a parent on another show, a performance
    class at either end — is refused with `ERR_PARENT_CLASS_LEVEL_INVALID`."

    Design: Corner/entities/class_creation_with_parent_from_another_show_returns_parent_class_level_invalid
    """
    set_clock("2026-08-10T09:00:00Z")
    club = register_club()

    first = apply_for_show(club)
    submit_show(first, club)
    approve_show(first)

    second = apply_for_show(club, show_name="Spring Trial", show_date="2026-09-19")
    submit_show(second, club)
    approve_show(second)
    foreign_parent = validate_success(
        api_client.create_class(
            create_group_class_payload(second["id"], class_code="G1"), SS_HEADERS
        ),
        201,
    )

    response = api_client.create_class(
        create_breed_class_payload(
            first["id"], class_code="B1", parent_class_id=foreign_parent["id"]
        ),
        SS_HEADERS,
    )
    validate_error(response, ApiErrorId.ERR_PARENT_CLASS_LEVEL_INVALID, 409)

    _, meta = validate_paginated(
        api_client.list_classes(SS_HEADERS, {"show_id": first["id"]})
    )
    assert meta["total_count"] == 0
