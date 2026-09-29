"""Half-open intervals on airtime, and a turnaround zone on top of them."""

from test_helpers import api_errors as e
from test_helpers import assertions as a
from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.test_users import FACILITIES_HEADERS, SCHEDULER_HEADERS


# ---------------------------------------------------------------------------
# Channel airtime: the buffer lives inside the footprint
# ---------------------------------------------------------------------------
def _channel_with_one_incumbent_evening_slot(client):
    """A first-come slot occupying 18:00 to 18:32 on a non-preempting channel."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    channel = fx.create_channel(client, call_sign="PATV1", preemption_enabled=False)
    programs = [
        fx.setup_approved_program(
            client, producer["id"], title=title, runtime_seconds=1800,
            is_live=False, required_crew_roles=[],
        )
        for title in ("Airtime X", "Airtime Y", "Airtime Z")
    ]
    incumbent = fx.book_slot(
        client, channel["id"], programs[0]["id"], "2026-08-20T18:00:00Z"
    )
    return channel, programs, incumbent


def test_a_slot_starting_at_the_incumbents_exclusive_end_is_admitted(client):
    """18:32 is the incumbent's exclusive end, so adjacency is not an overlap.

    PRD 3.4: "The slot's `end_at` is its `start_at` advanced by
    `occupied_seconds`, and the slot owns the half-open interval that begins at
    `start_at` and ends immediately before `end_at` — a slot beginning exactly
    when another ends does not overlap it."

    PRD 3.4: "An existing slot overlaps the candidate when that slot's `start_at`
    is strictly before the candidate's `end_at` and the candidate's `start_at` is
    strictly before that slot's `end_at`. When nothing overlaps, the booking is
    accepted outright."

    Design: Difficulty/resource_temporal_overlap/channel_airtime_half_open_footprint_admits_exact_adjacency
    """
    channel, programs, incumbent = _channel_with_one_incumbent_evening_slot(client)
    assert incumbent["occupied_seconds"] == 1920
    a.assert_instant_equals(incumbent["end_at"], "2026-08-20T18:32:00Z", "end_at")

    adjacent = a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(
                channel["id"], programs[1]["id"], "2026-08-20T18:32:00Z"
            ),
            SCHEDULER_HEADERS,
        )
    )

    assert adjacent["status"] == "SCHEDULED"
    assert adjacent["occupied_seconds"] == 1920
    a.assert_instant_equals(adjacent["end_at"], "2026-08-20T19:04:00Z", "end_at")
    a.assert_channel_ledger(fx.read_channel(client, channel["id"]), 3840, 0)


def test_a_start_one_minute_earlier_collides_with_the_buffer_tail(client):
    """18:31 falls inside the incumbent's footprint because the buffer is in it.

    PRD 3.4: "`occupied_seconds` is the program's `runtime_seconds` plus the
    channel's `inter_program_buffer_seconds`, and it is frozen on the slot at
    creation so that a later change to either input cannot retroactively move the
    schedule."

    PRD 3.4: "If no `series_id` was supplied, the booking is refused with
    `ERR_SLOT_WINDOW_CONFLICT` (409)."

    PRD 3.4: "`preemption_enabled` defaults to true; when it is set false, a
    series-priority challenger can never displace an incumbent on that channel."

    Design: Difficulty/resource_temporal_overlap/channel_airtime_half_open_footprint_admits_exact_adjacency
    """
    channel, programs, incumbent = _channel_with_one_incumbent_evening_slot(client)
    a.created_of(
        client.create_playback_slot(
            f.playback_slot_payload(channel["id"], programs[1]["id"], "2026-08-20T18:32:00Z"),
            SCHEDULER_HEADERS,
        )
    )

    response = client.create_playback_slot(
        f.playback_slot_payload(channel["id"], programs[2]["id"], "2026-08-20T18:31:00Z"),
        SCHEDULER_HEADERS,
    )

    a.error_of(response, e.ERR_SLOT_WINDOW_CONFLICT, 409)
    assert a.data_of(
        client.list_playback_slots(SCHEDULER_HEADERS, {"program_id": programs[2]["id"]})
    ) == []
    still_scheduled = fx.read_slot(client, incumbent["id"])
    assert still_scheduled["status"] == "SCHEDULED"
    a.assert_field_absent_or_null(still_scheduled, "preempted_by_slot_id")
    after = fx.read_channel(client, channel["id"])
    a.assert_channel_ledger(after, 3840, 0)
    assert after["slot_sequence_high"] == 2


# ---------------------------------------------------------------------------
# Studio resources: a turnaround zone on top of the overlap test
# ---------------------------------------------------------------------------
def _three_requested_reservations_on_a_single_slot_kit(client):
    """A one-slot kit with a thirty-minute turnaround and three pending requests."""
    producer = fx.setup_basic_certified_producer(
        client, score=88, legal_name="Ada Lovelace", email="ada@patv.example"
    )
    resource = fx.create_resource(
        client,
        resource_code="CAM-01",
        resource_class="FIELD_CAMERA_KIT",
        required_competency_code="STUDIO_FLOOR",
        capacity_slots=1,
        turnaround_minutes=30,
        base_deposit_cents=5000,
        replacement_value_cents=90000,
    )
    windows = (
        ("2026-08-08T10:00:00Z", "2026-08-08T12:00:00Z"),
        ("2026-08-08T12:00:00Z", "2026-08-08T14:00:00Z"),
        ("2026-08-08T12:30:00Z", "2026-08-08T14:30:00Z"),
    )
    reservations = [
        fx.request_reservation(client, producer["id"], resource["id"], start_at, end_at)
        for start_at, end_at in windows
    ]
    return producer, resource, reservations


def test_an_adjacent_reservation_is_refused_by_the_turnaround_exclusion_zone(client):
    """No interval overlap exists, so only the turnaround zone can refuse it.

    PRD 3.6: "Separately, and even where no overlap exists, the request is
    blocked when its `start_at` falls inside the `turnaround_minutes` window that
    follows the `end_at` of one of those reservations; a kit with a thirty-minute
    turnaround cannot be handed to the next producer twenty minutes after it came
    back."

    PRD 3.6: "The duration line is `base_deposit_cents` multiplied by the
    duration loading in basis points, divided by ten thousand, rounded half up."

    Design: Difficulty/resource_temporal_overlap/studio_resource_turnaround_exclusion_zone_blocks_adjacent_booking
    """
    producer, resource, reservations = _three_requested_reservations_on_a_single_slot_kit(client)

    first = fx.confirm_reservation(client, reservations[0]["id"])
    a.assert_cents(first["deposit_hold_cents"], 5250, "deposit_hold_cents")
    response = client.confirm_reservation(reservations[1]["id"], {}, FACILITIES_HEADERS)

    a.error_of(response, e.ERR_RESOURCE_OVERBOOKED, 409)
    refused = fx.read_reservation(client, reservations[1]["id"])
    assert refused["status"] == "REQUESTED"
    a.assert_cents(refused["deposit_hold_cents"], 0, "deposit_hold_cents")
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=5250)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 1


def test_a_start_at_the_exact_end_of_the_exclusion_zone_is_admitted(client):
    """12:30 is the exclusive end of the zone that opened at 12:00.

    PRD 3.6: "Room for the interval is judged against the asset's other
    reservations whose status is `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`.
    Two reservations overlap when the first's `start_at` is strictly before the
    second's `end_at` and the second's `start_at` is strictly before the first's
    `end_at` — the interval is half-open, so a booking that starts exactly when
    another ends does not overlap it."

    PRD 2.9: "A studio resource's `open_reservation_count` is the count of its
    reservations whose status is `CONFIRMED`, `CHECKED_OUT` or `DAMAGE_REVIEW`."

    Design: Difficulty/resource_temporal_overlap/studio_resource_turnaround_exclusion_zone_blocks_adjacent_booking
    """
    producer, resource, reservations = _three_requested_reservations_on_a_single_slot_kit(client)
    fx.confirm_reservation(client, reservations[0]["id"])
    a.error_of(
        client.confirm_reservation(reservations[1]["id"], {}, FACILITIES_HEADERS),
        e.ERR_RESOURCE_OVERBOOKED,
        409,
    )

    admitted = fx.confirm_reservation(client, reservations[2]["id"])

    assert admitted["status"] == "CONFIRMED"
    a.assert_cents(admitted["deposit_hold_cents"], 5250, "deposit_hold_cents")
    assert admitted["risk_bp"] == 0
    a.assert_producer_counters(fx.read_producer(client, producer["id"]), held=10500)
    assert fx.read_resource(client, resource["id"])["open_reservation_count"] == 2
