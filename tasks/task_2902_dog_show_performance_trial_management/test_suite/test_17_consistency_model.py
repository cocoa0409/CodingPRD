"""Immediate consistency: what the writing response already knows, and what the
first read of every touched row must already show."""

from test_helpers import api_client, validate_success
from test_helpers.assertions import (
    assert_entry,
    assert_instant_equals,
    assert_three_fractional_digits,
)
from test_helpers.factories import complete_class_payload
from test_helpers.fixtures import (
    read_class,
    read_dog,
    read_entry,
    read_show,
    setup_class_ready_to_judge,
    setup_show_with_class,
)
from test_helpers.test_users import make_judge_headers, make_show_secretary_headers


def test_confirmation_returns_the_armband_and_the_fee_in_its_own_response_body():
    """Nothing about confirmation is deferred, so the 200 body carries both values.

    PRD 2.8: "The service applies all of these effects within the request that
    triggered them — consistency is immediate, never deferred to a background job —
    and each affected resource has its own `updated_at` refreshed and its own
    `version` increased by one."

    PRD 3.5: "Otherwise the entry takes `armband_high_water` plus one and
    `armband_high_water` advances to that value, so the first confirmation of a show
    issues armband 1 from a high-water mark of 0."

    Design: Corner/consistency_model/confirmation_returns_the_armband_and_the_fee_in_its_own_response_body
    """
    context = setup_show_with_class(num_dogs=1, num_entries=1)
    klass, entry = context["klass"], context["entries"][0]
    assert entry["entry_status"] == "RECEIVED"
    assert entry["armband_number"] is None

    confirmed = validate_success(
        api_client.confirm_entry(entry["id"], make_show_secretary_headers()), 200
    )
    assert_entry(confirmed)
    assert confirmed["entry_status"] == "CONFIRMED"
    assert confirmed["armband_number"] == 1, "no re-read is needed to see the armband"
    assert confirmed["entry_fee_cents"] == 4663, "nor to see the assessed fee"
    assert confirmed["levy_cents"] == 263
    assert confirmed["net_fee_cents"] == 4663
    assert confirmed["fee_basis"] == "PROVISIONAL"
    assert confirmed["version"] == 2

    read_back = read_entry(entry)
    assert read_back == confirmed, (
        "the first read after the write repeats the write's own body exactly"
    )
    assert read_back["version"] == 2

    klass_row = read_class(klass)
    assert klass_row["entry_count"] == 1, "the class rollup is already current"
    assert klass_row["present_count"] == 0, "nobody has checked in yet"

    show = read_show(context["show"])
    assert show["confirmed_entry_count"] == 1
    assert show["armband_high_water"] == 1
    assert show["fee_charged_cents"] == 4663
    assert show["levy_total_cents"] == 263


def test_class_completion_fan_out_is_visible_on_the_first_read_of_every_touched_row():
    """The widest write in the domain lands entirely inside its own request.

    PRD 2.8: "The service applies all of these effects within the request that
    triggered them — consistency is immediate, never deferred to a background job —
    and each affected resource has its own `updated_at` refreshed and its own
    `version` increased by one."

    PRD 3.8: "A count of 0 or 1 dog awards 0 points; 2 to 4 dogs awards 1 point; 5
    to 9 dogs awards 2 points; 10 to 17 dogs awards 3 points; 18 to 29 dogs awards 4
    points; and 30 dogs or more awards 5 points."

    PRD 3.8: "For every dog that gained points, `championship_points_total` is
    re-derived as the sum of `points_awarded` over all of that dog's entries and
    `majors_count` is re-derived as the number of that dog's entries whose
    `points_awarded` is 2 or more, two points being the threshold at which a win
    counts as a major."

    Design: Corner/consistency_model/class_completion_fan_out_is_visible_on_the_first_read_of_every_touched_row
    """
    context = setup_class_ready_to_judge(num_dogs=2)
    klass, entries, judge = context["klass"], context["entries"], context["judge"]

    completed = validate_success(
        api_client.complete_class(
            klass["id"],
            complete_class_payload([entries[0]["id"], entries[1]["id"]]),
            make_judge_headers(judge["id"]),
        ),
        200,
    )
    assert completed["status"] == "COMPLETED"
    assert completed["counted_dog_count"] == 2, "both present dogs are counted"
    assert completed["base_points"] == 1, "two counted dogs falls in the 2-to-4 band"
    assert_three_fractional_digits(completed["completed_at"], "completed_at")
    assert_instant_equals(
        completed["completed_at"], "2026-09-12T10:00:00Z", "completed_at"
    )

    winner = read_entry(entries[0])
    assert winner["entry_status"] == "JUDGED"
    assert winner["placement"] == 1
    assert winner["points_awarded"] == 1

    runner_up = read_entry(entries[1])
    assert runner_up["entry_status"] == "JUDGED"
    assert runner_up["placement"] == 2
    assert runner_up["points_awarded"] == 0

    dog = read_dog(context["dogs"][0])
    assert dog["championship_points_total"] == 1
    assert dog["majors_count"] == 0, "one point is below the two-point major threshold"

    assert read_show(context["show"])["points_awarded_total"] == 1
