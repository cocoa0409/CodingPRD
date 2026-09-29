"""Rating a billable interval, and the three guards that protect a care
manager's working day.
"""
from test_helpers import (
    PRACTICE_ADMIN,
    api_client,
    create_time_entry_payload,
    discharge_client,
    get_success_data,
    log_time_entry,
    make_care_manager_headers,
    open_crisis_episode,
    read_client,
    register_care_manager,
    register_client,
    set_logical_clock,
    validate_error,
    validate_paginated,
)


def _crisis_practice():
    """Clock at 2026-08-06, a quarter-hour client, and one OPEN fall episode."""
    set_logical_clock("2026-08-06T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    client = register_client(
        full_name="Eleanor Ashgrove-Petrakis",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
        travel_billing_pct=50,
    )
    episode = open_crisis_episode(
        client["id"], care_manager["id"], trigger_type="FALL"
    )
    return care_manager, client, episode


def test_01_the_four_rating_factors_are_derived_independently():
    """A 95-minute crisis response starting at 19:00 UTC on a quarter-hour client
    derives 105 rounded minutes, a 1.5 crisis premium and a 1.20 after-hours
    factor, each from its own input.

    PRD: "`rounded_minutes` is `raw_minutes` rounded **up** to the next multiple of the client's `billing_increment_min`, so a 22-minute call on a quarter-hour client bills as 30 minutes."

    Design: Difficulty/combinatorial_formula/time_entry_four_factor_nonlinear_composition_mode_a
    """
    care_manager, client, episode = _crisis_practice()
    entry = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-06T19:00:00Z",
        "2026-08-06T20:35:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert entry["service_date"] == "2026-08-06"
    assert entry["raw_minutes"] == 95
    assert entry["rounded_minutes"] == 105
    assert float(entry["rate_multiplier"]) == 1.5
    assert float(entry["after_hours_factor"]) == 1.20
    assert entry["status"] == "DRAFT"


def test_02_the_billable_amount_is_one_product_rounded_exactly_once():
    """105 minutes at 22,500 cents an hour with a 1.5 premium and a 1.20
    after-hours factor composes to 70,875 cents, and not to the 70,876 an
    intermediate rounding would produce.

    PRD: "`billable_amount_cents` is then composed as a single product and rounded exactly once: multiply `rounded_minutes` by the care manager's `hourly_rate_cents`, by `rate_multiplier` and by `after_hours_factor`, divide by 60 to convert minutes to hours, and round the resulting figure half up to whole cents."

    Design: Difficulty/combinatorial_formula/time_entry_four_factor_nonlinear_composition_mode_a
    """
    care_manager, client, episode = _crisis_practice()
    entry = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-06T19:00:00Z",
        "2026-08-06T20:35:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert entry["billable_amount_cents"] == 70_875
    assert entry["billable_amount_cents"] != 70_876
    assert isinstance(entry["billable_amount_cents"], int)


def test_03_the_rated_amount_lands_on_the_client_as_unbilled_accrual():
    """A freshly logged draft entry is inside the accrual input set, so the
    client's `unbilled_accrual_cents` carries the whole rated amount.

    PRD: "Alongside the retainer, the client's `unbilled_accrual_cents` is the sum of `billable_amount_cents` over that client's time entries whose `status` is `DRAFT`, `SUBMITTED` or `APPROVED`; entries that are `REJECTED`, `INVOICED` or `VOIDED` contribute nothing."

    Design: Difficulty/combinatorial_formula/time_entry_four_factor_nonlinear_composition_mode_a
    """
    care_manager, client, episode = _crisis_practice()
    assert read_client(client["id"])["unbilled_accrual_cents"] == 0
    log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-06T19:00:00Z",
        "2026-08-06T20:35:00Z",
        service_type="CRISIS_RESPONSE",
        service_location_id="HOSPITAL_A",
        crisis_episode_id=episode["id"],
    )
    assert read_client(client["id"])["unbilled_accrual_cents"] == 70_875


def _calendar_practice():
    """Clock at 2026-08-16 and one standing 14:00-15:00 entry at CLIENT_HOME."""
    set_logical_clock("2026-08-16T09:00:00Z")
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    client = register_client(
        full_name="Eleanor Ashgrove-Petrakis",
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
    )
    first = log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-16T14:00:00Z",
        "2026-08-16T15:00:00Z",
        service_location_id="CLIENT_HOME",
    )
    return care_manager, client, first


def test_04_an_interval_straddling_a_standing_entry_is_an_overlap():
    """A second interval starting inside the first is rejected, because the two
    half-open intervals genuinely intersect.

    PRD: "First, the entry may not overlap another entry of the **same care manager** whose `status` is `DRAFT`, `SUBMITTED`, `APPROVED` or `INVOICED`; time-entry intervals are **half-open**, covering `start_at` up to but not including `end_at`, so an entry that begins at the exact instant another ends does not overlap."

    Design: Difficulty/resource_temporal_overlap/care_manager_calendar_half_open_overlap_and_travel_buffer
    """
    care_manager, client, _first = _calendar_practice()
    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-16T14:30:00Z",
            "2026-08-16T15:30:00Z",
            service_location_id="CLIENT_HOME",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, "ERR_TIME_ENTRY_OVERLAP", 409)

    listing = api_client.list_time_entries(
        PRACTICE_ADMIN,
        {"care_manager_id": care_manager["id"], "service_date": "2026-08-16"},
    )
    entries, meta = validate_paginated(listing)
    assert meta["total_count"] == 1
    assert len(entries) == 1


def test_05_an_interval_beginning_where_the_previous_one_ends_is_accepted():
    """Because the intervals are half-open, an entry starting at the exact
    instant the previous one ends does not overlap and rates normally.

    PRD: "`raw_minutes` is the number of whole minutes between `start_at` and `end_at`, with any partial minute discarded downward."

    Design: Difficulty/resource_temporal_overlap/care_manager_calendar_half_open_overlap_and_travel_buffer
    """
    care_manager, client, _first = _calendar_practice()
    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-16T15:00:00Z",
            "2026-08-16T15:45:00Z",
            service_location_id="CLIENT_HOME",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    abutting = get_success_data(response, 201)
    assert abutting["rounded_minutes"] == 45
    assert abutting["billable_amount_cents"] == 16_875


def test_06_a_change_of_location_with_no_gap_violates_the_travel_buffer():
    """An entry at a different location beginning the instant the previous one
    ends leaves the care manager no time to travel, and is refused.

    PRD: "Second, when the nearest non-overlapping neighbouring entry of that same care manager, drawn from the same four statuses, carries a different `service_location_id`, the gap between the two intervals must be at least half an hour — 30 minutes — because the care manager has to physically travel; a gap of exactly 30 minutes passes, and anything shorter is rejected with `ERR_TRAVEL_BUFFER_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/care_manager_calendar_half_open_overlap_and_travel_buffer
    """
    care_manager, client, _first = _calendar_practice()
    log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-16T15:00:00Z",
        "2026-08-16T15:45:00Z",
        service_location_id="CLIENT_HOME",
    )
    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-16T15:45:00Z",
            "2026-08-16T16:00:00Z",
            service_location_id="HOSPITAL_A",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, "ERR_TRAVEL_BUFFER_VIOLATION", 409)


def test_07_a_gap_of_exactly_thirty_minutes_clears_the_travel_buffer():
    """Half an hour of travel is enough; the accepted day then holds exactly
    three entries whose rated amounts sum onto the client's accrual.

    PRD: "Third, the sum of `rounded_minutes` over that care manager's entries sharing the same `service_date`, across every client and drawn from the same four statuses, including the candidate, may not exceed ten hours — 600 minutes; a total of exactly 600 minutes passes and anything beyond it is rejected with `ERR_DAILY_CAP_EXCEEDED`."

    Design: Difficulty/resource_temporal_overlap/care_manager_calendar_half_open_overlap_and_travel_buffer
    """
    care_manager, client, _first = _calendar_practice()
    log_time_entry(
        client["id"],
        care_manager["id"],
        "2026-08-16T15:00:00Z",
        "2026-08-16T15:45:00Z",
        service_location_id="CLIENT_HOME",
    )
    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-16T16:15:00Z",
            "2026-08-16T17:00:00Z",
            service_location_id="HOSPITAL_A",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    travelled = get_success_data(response, 201)
    assert travelled["rounded_minutes"] == 45
    assert travelled["billable_amount_cents"] == 16_875

    listing = api_client.list_time_entries(
        PRACTICE_ADMIN,
        {"care_manager_id": care_manager["id"], "service_date": "2026-08-16"},
    )
    entries, meta = validate_paginated(listing)
    assert meta["total_count"] == 3
    assert len(entries) == 3
    assert read_client(client["id"])["unbilled_accrual_cents"] == 56_250


def _client_at_the_daily_cap(full_name, service_date):
    """A quarter-hour client carrying exactly 600 rounded minutes on one date."""
    care_manager = register_care_manager(
        full_name="Dana Whitfield", hourly_rate_cents=22_500
    )
    client = register_client(
        full_name=full_name,
        residence_setting="PRIVATE_HOME",
        billing_increment_min=15,
    )
    log_time_entry(
        client["id"],
        care_manager["id"],
        f"{service_date}T09:00:00Z",
        f"{service_date}T18:00:00Z",
        service_location_id="CLIENT_HOME",
    )
    log_time_entry(
        client["id"],
        care_manager["id"],
        f"{service_date}T18:00:00Z",
        f"{service_date}T19:00:00Z",
        service_location_id="CLIENT_HOME",
    )
    return care_manager, client


def test_08_a_discharged_client_is_reported_before_the_daily_cap():
    """The candidate interval breaches the ten-hour cap *and* addresses a
    discharged client; the earlier rung of the ladder — client-status
    compatibility — is the one reported.

    PRD: "Time may not be logged against a `DISCHARGED` client; that attempt is rejected with `ERR_CLIENT_NOT_IN_SERVICE`."

    Design: Difficulty/priority_pair_validation_conflict/discharged_client_beats_daily_cap_on_time_entry_creation
    """
    set_logical_clock("2026-08-10T09:00:00Z")
    care_manager, client = _client_at_the_daily_cap(
        "Eleanor Ashgrove-Petrakis", "2026-08-10"
    )
    discharged = discharge_client(client["id"], reason="Client died; engagement closed.")
    assert discharged["status"] == "DISCHARGED"

    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-10T19:00:00Z",
            "2026-08-10T19:15:00Z",
            service_location_id="CLIENT_HOME",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, "ERR_CLIENT_NOT_IN_SERVICE", 409)

    listing = api_client.list_time_entries(
        PRACTICE_ADMIN,
        {"care_manager_id": care_manager["id"], "service_date": "2026-08-10"},
    )
    _entries, meta = validate_paginated(listing)
    assert meta["total_count"] == 2


def test_09_an_in_service_client_at_the_cap_reports_the_fiscal_guard_instead():
    """With the client-status rung satisfied, the identical over-cap interval
    falls through to the daily billable cap, which proves the pairing is an
    ordering and not a single rule wearing two names.

    PRD: "Checks are evaluated in the ascending order given below and **the first failure wins** — a request that violates three rules reports only the earliest one."

    Design: Difficulty/priority_pair_validation_conflict/discharged_client_beats_daily_cap_on_time_entry_creation
    """
    set_logical_clock("2026-08-10T09:00:00Z")
    care_manager, client = _client_at_the_daily_cap(
        "Frances Achterberg-Quist", "2026-08-11"
    )
    assert read_client(client["id"])["status"] == "PROSPECT"

    response = api_client.create_time_entry(
        create_time_entry_payload(
            client["id"],
            care_manager["id"],
            "2026-08-11T19:00:00Z",
            "2026-08-11T19:15:00Z",
            service_location_id="CLIENT_HOME",
        ),
        make_care_manager_headers(care_manager["id"]),
    )
    validate_error(response, "ERR_DAILY_CAP_EXCEEDED", 422)

    listing = api_client.list_time_entries(
        PRACTICE_ADMIN,
        {"care_manager_id": care_manager["id"], "service_date": "2026-08-11"},
    )
    _entries, meta = validate_paginated(listing)
    assert meta["total_count"] == 2
