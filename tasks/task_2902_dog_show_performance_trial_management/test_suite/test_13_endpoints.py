"""Endpoint round-trips: what a write leaves behind for the matching read to find."""

from test_helpers import api_client, validate_error, validate_success
from test_helpers.assertions import (
    assert_handler,
    assert_instant_equals,
    assert_performance_run,
    assert_three_fractional_digits,
)
from test_helpers.constants import SETUP_CLOCK_INSTANT
from test_helpers.factories import (
    create_handler_payload,
    create_performance_run_payload,
    temperature_reading_payload,
)
from test_helpers.fixtures import (
    apply_for_show,
    read_class,
    read_dog,
    read_entry,
    read_show,
    read_show_version,
    register_club,
    set_clock,
    setup_show_with_class,
)
from test_helpers.test_users import (
    make_judge_headers,
    make_sanction_officer_headers,
    make_show_secretary_headers,
)


def test_handler_registration_round_trips_through_the_read_endpoint():
    """The read row repeats the write row, defaults and all.

    PRD 3.1: "A handler's `status` defaults to `ACTIVE`; a `SUSPENDED` handler may
    neither enter dogs nor file protests, and the `suspension_reason` field
    records why."

    PRD 2.4: "On creation, `updated_at` equals `created_at` and `version` is 1."

    Design: Corner/endpoints/handler_registration_round_trips_through_the_read_endpoint
    """
    set_clock(SETUP_CLOCK_INSTANT)

    created = validate_success(
        api_client.create_handler(
            create_handler_payload(
                handler_name="Bo Trent", member_number="M-1002", region_code="NE"
            ),
            make_sanction_officer_headers(),
        ),
        201,
    )
    assert_handler(created)
    assert created["handler_name"] == "Bo Trent"
    assert created["status"] == "ACTIVE"
    assert created["suspension_reason"] is None
    assert created["version"] == 1
    assert_instant_equals(created["created_at"], SETUP_CLOCK_INSTANT, "handler.created_at")
    assert_three_fractional_digits(created["created_at"], "handler.created_at")
    assert_instant_equals(created["updated_at"], SETUP_CLOCK_INSTANT, "handler.updated_at")

    read_back = validate_success(
        api_client.get_handler(created["id"], make_show_secretary_headers()), 200
    )
    assert read_back["id"] == created["id"]
    assert read_back["member_number"] == "M-1002"
    assert read_back["region_code"] == "NE"
    assert read_back["status"] == "ACTIVE"
    assert read_back["version"] == 1
    assert read_back == created


def test_open_day_moves_the_approved_show_into_progress_and_bumps_its_version():
    """A bodiless action whose only visible effects are on the show itself.

    PRD 3.2: "On the morning of the event the show secretary opens the day, moving
    the show `APPROVED → IN_PROGRESS`. This is a compound gate: at least one class
    must exist for the show, and every one of the show's classes must have reached
    `CLOSED` or `SCHEDULED`, which in practice means entries have been closed
    everywhere."

    Design: Corner/endpoints/open_day_moves_the_approved_show_into_progress_and_bumps_its_version
    """
    context = setup_show_with_class(
        num_dogs=1, num_entries=1, confirm_entries=True, close_class=True
    )
    show, klass, entry = context["show"], context["klass"], context["entries"][0]
    show_version = read_show_version(show)

    opened = validate_success(
        api_client.open_show_day(show["id"], make_show_secretary_headers()), 200
    )
    assert opened["status"] == "IN_PROGRESS"
    assert opened["version"] == show_version + 1

    reread = read_show(show)
    assert reread["status"] == "IN_PROGRESS"
    assert reread["version"] == show_version + 1
    assert read_class(klass)["status"] == "CLOSED"
    assert read_entry(entry)["entry_status"] == "CONFIRMED"


def test_performance_run_takes_its_discipline_from_the_class_not_from_the_request():
    """The run body never names a discipline, so the server walks entry to class.

    PRD 3.8: "The run's `discipline` is not supplied — it is copied from the
    discipline of the entry's class at creation and is what selects the scoring
    branch."

    PRD 3.8: "For the `RALLY` discipline, `total_faults` is the
    `obedience_deductions` plus 3.0 points for each scored fault plus the
    whole-second `time_faults`, `final_score` is 100.0 less that total floored at
    0.0, and the run is `QUALIFIED` when the final score is 70.0 or higher and
    `NQ` otherwise."

    Design: Corner/endpoints/performance_run_takes_its_discipline_from_the_class_not_from_the_request
    """
    context = setup_show_with_class(
        num_dogs=1,
        num_entries=1,
        confirm_entries=True,
        judge_overrides={
            "judge_number": "J-77",
            "full_name": "Rex Calder",
            "approved_performance_disciplines": ["RALLY"],
        },
        show_overrides={"show_type": "PERFORMANCE"},
        class_level="PERFORMANCE",
        discipline="RALLY",
        close_class=True,
        open_show=True,
        check_in_attendance="PRESENT",
    )
    entry, judge, dog = context["entries"][0], context["judge"], context["dogs"][0]

    run = validate_success(
        api_client.create_performance_run(
            create_performance_run_payload(
                entry["id"], 90.0, 60.0, 58.0,
                faults_count=4, obedience_deductions=6.0,
            ),
            make_judge_headers(judge["id"]),
        ),
        201,
    )
    assert_performance_run(run)
    assert run["discipline"] == "RALLY"
    assert run["entry_id"] == entry["id"]
    assert float(run["time_faults"]) == 0.0
    assert float(run["total_faults"]) == 18.0
    assert float(run["final_score"]) == 82.0
    assert run["run_result"] == "QUALIFIED"
    assert run["title_leg_awarded"] is True

    assert read_dog(dog)["qualifying_leg_counts"]["RALLY"] == 1


def test_temperature_reading_on_a_draft_show_returns_invalid_state():
    """The welfare log is a self-loop declared only on the two live statuses.

    PRD 3.7: "A reading may be taken while the show is `APPROVED` or while it is
    `IN_PROGRESS`; in both cases it increases the show's
    `temperature_reading_count` by one, rewrites `current_heat_index_c` and
    `current_advisory_level`, and increases the show's `version` by one."

    PRD 2.9 rung 8: "Every other undeclared transition, including every repeat of
    an already-applied action and every attempt to leave a terminal state, gives
    the generic `ERR_INVALID_STATE`."

    Design: Corner/endpoints/temperature_reading_on_a_draft_show_returns_invalid_state
    """
    set_clock(SETUP_CLOCK_INSTANT)
    show = apply_for_show(register_club())
    assert show["status"] == "DRAFT"

    response = api_client.record_temperature_reading(
        show["id"], temperature_reading_payload(29.0, 65), make_show_secretary_headers()
    )
    validate_error(response, "ERR_INVALID_STATE", 409)

    unchanged = read_show(show)
    assert unchanged["status"] == "DRAFT"
    assert unchanged["temperature_reading_count"] == 0
    assert unchanged["current_advisory_level"] is None
    assert unchanged["current_heat_index_c"] is None
    assert unchanged["version"] == 1
