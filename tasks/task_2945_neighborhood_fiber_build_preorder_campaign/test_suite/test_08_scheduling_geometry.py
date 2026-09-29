"""Buffered pairwise intervals, raw-window bury concurrency and per-date crew capacity."""

from test_helpers import (
    COORDINATOR,
    ApiErrorId,
    api_client,
    assert_crew_load,
    conversion_payload,
    get_success_data,
    install_appointment_payload,
    make_appointment,
    make_crew,
    make_subscriber_headers,
    read_crew,
    read_crew_version,
    setup_construction_ready_zone,
    validate_error,
    validate_success,
)

DAY = "2026-10-05"


def _at(hhmm: str) -> str:
    return f"{DAY}T{hhmm}:00Z"


def _zone_with_three_converted_preorders(**kwargs):
    """A zone mid-build whose three preorders have all been converted to install orders."""
    base = setup_construction_ready_zone(
        preorder_count=3, household_count=10, threshold_pct=10.0, **kwargs
    )
    converted = []
    for index, preorder in enumerate(base["preorders"]):
        account = base["accounts"][index]
        converted.append(
            get_success_data(
                api_client.convert_preorder(
                    preorder["id"],
                    conversion_payload("BURY"),
                    make_subscriber_headers(account["id"]),
                )
            )
        )
    base["converted_preorders"] = converted
    return base


def test_daily_capacity_accepts_an_exact_fit_at_the_crew_limit():
    """Two windows occupying 150 and 90 minutes fill a 240-minute day precisely.

    PRD 3.8: "The **daily capacity gate** sums `occupied_minutes` over the crew's `SCHEDULED`
    appointments whose `window_start_at` falls on the same UTC calendar date as the new
    booking's `window_start_at`, adds the new appointment's own `occupied_minutes`, and
    requires the result to be at most the crew's `daily_capacity_minutes`; an exact fit at
    capacity is accepted, and exceeding it is `ERR_CREW_DAILY_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/crew_daily_capacity_exact_fit_accepted_next_minute_rejected
    """
    base = _zone_with_three_converted_preorders()
    crew = make_crew(
        name="Bury Crew 1",
        crew_type="BURY",
        travel_buffer_minutes=30,
        daily_capacity_minutes=240,
    )
    orders = base["converted_preorders"]

    first = make_appointment(orders[0]["id"], crew["id"], _at("09:00"), _at("11:00"))
    second = make_appointment(orders[1]["id"], crew["id"], _at("12:00"), _at("13:00"))

    assert first["occupied_minutes"] == 150, first["occupied_minutes"]
    assert second["occupied_minutes"] == 90, second["occupied_minutes"]
    assert_crew_load(read_crew(crew["id"]), 240, 2)


def test_one_more_window_past_the_exact_fit_is_refused_for_capacity():
    """A third 60-minute booking would reach 300 on a 240-minute crew, so it is rejected.

    PRD 3.8: "From those instants the appointment's `occupied_minutes` is derived as the whole
    minutes between start and end **plus** the crew's `travel_buffer_minutes`, and that single
    figure is the unit of both the conflict geometry and the daily capacity accounting."

    Design: Difficulty/boundary_precision_check/crew_daily_capacity_exact_fit_accepted_next_minute_rejected
    """
    base = _zone_with_three_converted_preorders()
    crew = make_crew(
        name="Bury Crew 1",
        crew_type="BURY",
        travel_buffer_minutes=30,
        daily_capacity_minutes=240,
    )
    orders = base["converted_preorders"]
    make_appointment(orders[0]["id"], crew["id"], _at("09:00"), _at("11:00"))
    make_appointment(orders[1]["id"], crew["id"], _at("12:00"), _at("13:00"))

    response = api_client.create_install_appointment(
        install_appointment_payload(
            orders[2]["id"],
            crew["id"],
            _at("14:00"),
            _at("14:30"),
            read_crew_version(crew["id"]),
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_CREW_DAILY_CAPACITY_EXCEEDED)
    assert_crew_load(read_crew(crew["id"]), 240, 2)


def test_a_start_one_minute_inside_the_buffered_end_is_a_crew_conflict():
    """An 11:29 start collides with an 11:00 end carrying a thirty-minute trailing buffer.

    PRD 3.8: "A conflict exists against an appointment that is `SCHEDULED` on the same crew
    when the new window's start falls strictly before that appointment's end advanced by the
    buffer *and* that appointment's start falls strictly before the new window's end advanced
    by the buffer."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_halfopen_interval_rejects_11_29_accepts_11_30
    """
    base = _zone_with_three_converted_preorders()
    crew = make_crew(name="Bury Crew 1", crew_type="BURY", travel_buffer_minutes=30)
    orders = base["converted_preorders"]
    make_appointment(orders[0]["id"], crew["id"], _at("09:00"), _at("11:00"))

    response = api_client.create_install_appointment(
        install_appointment_payload(
            orders[1]["id"],
            crew["id"],
            _at("11:29"),
            _at("12:29"),
            read_crew_version(crew["id"]),
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_CREW_WINDOW_CONFLICT)
    assert_crew_load(read_crew(crew["id"]), 150, 1)


def test_a_start_exactly_on_the_buffered_end_is_accepted():
    """An 11:30 start meets the buffered edge exactly, so back-to-back-plus-buffer is legal.

    PRD 3.8: "A new start exactly equal to an existing end advanced by the buffer is therefore
    not a conflict, while anything earlier is `ERR_CREW_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/crew_buffered_halfopen_interval_rejects_11_29_accepts_11_30
    """
    base = _zone_with_three_converted_preorders()
    crew = make_crew(name="Bury Crew 1", crew_type="BURY", travel_buffer_minutes=30)
    orders = base["converted_preorders"]
    make_appointment(orders[0]["id"], crew["id"], _at("09:00"), _at("11:00"))

    response = api_client.create_install_appointment(
        install_appointment_payload(
            orders[1]["id"],
            crew["id"],
            _at("11:30"),
            _at("12:30"),
            read_crew_version(crew["id"]),
        ),
        COORDINATOR,
    )

    booked = validate_success(response, 201)
    assert booked["status"] == "SCHEDULED", booked["status"]
    assert booked["occupied_minutes"] == 90, booked["occupied_minutes"]
    assert_crew_load(read_crew(crew["id"]), 240, 2)


def _three_crews_with_two_overlapping_digs():
    """Two long bury windows held by two different crews, overlapping between 10:00 and 12:00."""
    base = _zone_with_three_converted_preorders()
    orders = base["converted_preorders"]
    crews = [
        make_crew(name=f"Bury Crew {index + 1}", crew_type="BURY")
        for index in range(3)
    ]
    make_appointment(orders[0]["id"], crews[0]["id"], _at("09:00"), _at("12:00"))
    make_appointment(orders[1]["id"], crews[1]["id"], _at("10:00"), _at("13:00"))
    base["crews"] = crews
    return base


def test_bury_concurrency_counts_raw_overlaps_across_every_crew_in_the_zone():
    """A third dig inside the shared 10:30 to 11:30 stretch meets a cap of two.

    PRD 3.8: "That count must be strictly less than the zone's `max_concurrent_bury_ops`,
    otherwise `ERR_ZONE_BURY_CONCURRENCY_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/zone_bury_concurrency_counts_raw_windows_not_buffered_ones
    """
    base = _three_crews_with_two_overlapping_digs()
    orders = base["converted_preorders"]
    third_crew = base["crews"][2]

    response = api_client.create_install_appointment(
        install_appointment_payload(
            orders[2]["id"],
            third_crew["id"],
            _at("10:30"),
            _at("11:30"),
            read_crew_version(third_crew["id"]),
        ),
        COORDINATOR,
    )

    validate_error(response, ApiErrorId.ERR_ZONE_BURY_CONCURRENCY_EXCEEDED)
    assert_crew_load(read_crew(third_crew["id"]), 0, 0)


def test_a_window_clear_of_every_raw_dig_is_accepted_despite_the_buffers():
    """A 13:00 start clears both raw windows even though buffered ends run to 13:30.

    PRD 3.8: "Note the deliberate asymmetry: the pairwise gate buffers its intervals, this one
    does not, and this one is measured across every crew in the zone while the pairwise gate is
    scoped to a single crew."

    Design: Difficulty/resource_temporal_overlap/zone_bury_concurrency_counts_raw_windows_not_buffered_ones
    """
    base = _three_crews_with_two_overlapping_digs()
    orders = base["converted_preorders"]
    crews = base["crews"]

    response = api_client.create_install_appointment(
        install_appointment_payload(
            orders[2]["id"],
            crews[2]["id"],
            _at("13:00"),
            _at("14:00"),
            read_crew_version(crews[2]["id"]),
        ),
        COORDINATOR,
    )

    booked = validate_success(response, 201)
    assert booked["occupied_minutes"] == 90, booked["occupied_minutes"]
    assert_crew_load(read_crew(crews[0]["id"]), 210, 1)
    assert_crew_load(read_crew(crews[1]["id"]), 210, 1)
    assert_crew_load(read_crew(crews[2]["id"]), 90, 1)
